"""The checks of `relay_stack.py check` and the capture listing of `relay_stack.py captures`.

- health: the relay runs, its migrations are in `_sqlx_migrations`, Redis answers, the TLS front's certificate
  verifies against the stack's CA and the relay answers through it.
- forward: tools/bench/relay_load.py drives fake devices through the TLS front: register, pair, /v1/relay, text and
  binary frames forwarded to the peer (CONN-03 API 6).
- push: push_checks.py.
- android: the real app registered (POST /v1/devices), authenticated (HLAUTH1 → JWT) and opened /v1/relay: its row
  in `devices`, the TLS front's lines with the OkHttp User-Agent, the relay's access log, its presence in Redis.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import push_checks
import push_crypto
from capture_log import read_captures
from check_report import Result, excerpt, offset, summarize
from stack_config import RELAY_DIR, SHARED_TOOLS, Layout
from stack_processes import StackError, port_open, psql, recorded, redis_command
from stack_rest import RelayRest, error_code

FAKE_VERSIONS = ("(e2e)", "(load)")


def check_health(layout: Layout, info: dict, _wait_s: float) -> list[Result]:
    relay_log = Path(info["relay"]["log"])
    listening = excerpt(relay_log, 0, r"migrations applied; listening on", 1)
    pid = recorded(layout, "relay")
    results = [Result("relay process running and listening", bool(pid) and bool(listening),
                      [f"pid {pid}"] + listening)]
    try:
        rows = psql(layout, "SELECT version, description, success FROM _sqlx_migrations ORDER BY version").splitlines()
        tables = psql(layout, "SELECT string_agg(table_name, ',' ORDER BY table_name) FROM information_schema.tables "
                              "WHERE table_schema = 'public'").strip()
    except StackError as error:
        return results + [Result("database migrations", False, [str(error)])]
    files = sorted(p.name.split("_", 1)[0] for p in (RELAY_DIR / "migrations").glob("*.sql"))
    applied = {row.split("|")[0]: row.split("|")[-1] for row in rows if row}
    ok = files and all(applied.get(v) == "t" for v in files)
    results.append(Result("database has every migration of relay/migrations", bool(ok),
                          [f"_sqlx_migrations (version|description|success): {'; '.join(rows)}", f"migration files: {', '.join(files)}",
                           f"tables: {tables}"]))
    pong = redis_command(layout, "PING")
    results.append(Result("Redis answers", pong == "+PONG", [f"PING → {pong}"]))
    rest = RelayRest(info["relay"]["https"], info["tls"]["ca_cert"])
    start = offset(relay_log)
    unknown = str(uuid.uuid4())
    try:
        status, reply = rest.call("POST", "/v1/auth/challenge", {"device_id": unknown})
        answer = f"{status} {error_code(reply)}"
    except OSError as error:
        status, answer = 0, f"{type(error).__name__}: {error}"
    time.sleep(0.2)
    results.append(Result("relay answers through the TLS front (certificate verified against the stack CA)",
                          status == 404 and answer.endswith("DEVICE_NOT_FOUND"),
                          [f"POST {info['relay']['https']}/v1/auth/challenge (unknown device) → {answer}"]
                          + excerpt(relay_log, start, r"/v1/auth/challenge", 2)))
    mocks = {"mock APNs": int(info["apns"]["url"].rsplit(":", 1)[1]), "mock FCM": int(info["fcm"]["url"].rsplit(":", 1)[1])}
    results.append(Result("mock APNs and FCM listening", all(port_open(p) for p in mocks.values()),
                          [f"{k} 127.0.0.1:{v}" for k, v in mocks.items()]))
    return results


def check_forward(layout: Layout, info: dict, _wait_s: float) -> list[Result]:
    script = SHARED_TOOLS / "bench" / "relay_load.py"
    front_log, relay_log = Path(info["tls"]["front_log"]), Path(info["relay"]["log"])
    starts = offset(front_log), offset(relay_log)
    argv = [sys.executable, str(script), "--relay", info["relay"]["https"], "--devices", "4", "--frames", "6",
            "--interval-ms", "50", "--binary", "--settle-s", "0.5", "--drain-s", "5", "--cleanup", "--json"]
    env = {**os.environ, **info["tls"]["python_env"]}
    done = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=180)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        return [Result("forwarding between fake paired devices (relay_load.py)", False,
                       [f"relay_load.py exit {done.returncode}: {done.stderr.strip()[-600:]}"])]
    ok = (report["connected"] == report["devices"] and not report["failures"] and not report["relay_errors"]
          and not report["unexpected_closes"] and not any(report["lost"].values()) and all(report["sent"].values()))
    evidence = [f"{report['devices']} devices: registered {report['registered']}, pairs {report['pairs']}, "
                f"connected {report['connected']}, presence frames {report['presence_frames']}",
                f"frames sent {report['sent']}, received {report['received']}, lost {report['lost']}",
                f"failures {report['failures'] or 'none'}, relay errors {report['relay_errors'] or 'none'}, "
                f"unexpected closes {report['unexpected_closes'] or 'none'}"]
    for name in ("forward_text", "forward_binary"):
        d = report.get(name)
        if d:
            evidence.append(f"{name}: n={d['count']} p50={d['p50_ms']} ms p95={d['p95_ms']} ms max={d['max_ms']} ms")
    evidence += excerpt(front_log, starts[0], r"/v1/relay", 4)
    evidence += excerpt(relay_log, starts[1], r"/v1/relay", 4)
    return [Result("forwarding between fake paired devices through the TLS front (relay_load.py)", ok, evidence)]


def _android_rows(layout: Layout) -> list[list[str]]:
    rows = psql(layout, "SELECT device_id, app_version, coalesce(push_provider, '-'), "
                        "to_char(created_at, 'HH24:MI:SS'), to_char(last_seen_at, 'HH24:MI:SS') FROM devices "
                        "WHERE platform = 'android' ORDER BY created_at")
    return [r.split("|") for r in rows.splitlines() if r and not any(v in r for v in FAKE_VERSIONS)]


def check_android(layout: Layout, info: dict, wait_s: float) -> list[Result]:
    front_log, relay_log = Path(info["tls"]["front_log"]), Path(info["relay"]["log"])
    deadline = time.monotonic() + wait_s
    rows = _android_rows(layout)
    while not rows and time.monotonic() < deadline:
        time.sleep(2)
        rows = _android_rows(layout)
    okhttp = excerpt(front_log, 0, r"ua='okhttp", 200)
    refused = excerpt(front_log, 0, r"TLS handshake failed", 10)

    def lines(path_rx: str, statuses: str) -> list[str]:
        return [line for line in okhttp if f" {path_rx} " in line and line.split(f" {path_rx} ", 1)[1][:3] in statuses]

    registered, challenged = lines("/v1/devices", ("200", "201")), lines("/v1/auth/challenge", ("200",))
    token, relay_ws = lines("/v1/auth/token", ("200",)), lines("/v1/relay", ("101",))
    device_id = rows[-1][0] if rows else ""
    results = [Result("android app registered with the relay (POST /v1/devices, HLREG1)", bool(rows and registered),
                      [f"devices row: {' | '.join(r)}" for r in rows] + registered[-3:] + refused)]
    results.append(Result("android app authenticated (challenge → HLAUTH1 signature → JWT)",
                          bool(rows and challenged and token), challenged[-2:] + token[-2:]))
    presence = redis_command(layout, "EXISTS", f"presence:{device_id}") if device_id else ""
    results.append(Result("android app opened /v1/relay (WebSocket 101)", bool(relay_ws),
                          relay_ws[-3:] + [f"Redis EXISTS presence:<its device_id> → {presence} (1 = connected now)"]))
    if device_id:
        pairs = psql(layout, "SELECT p.pair_id, d.platform, p.revoked_at IS NULL FROM pairs p JOIN devices d ON "
                             f"d.device_id = p.device_b WHERE p.device_a = '{device_id}'").splitlines()
        results.append(Result("pairs the app registered on the relay (PAIR-01 API 8), informational", True,
                              [f"pair_id | peer platform | active: {row}" for row in pairs] or ["none yet"]))
    results.append(Result("relay access log for the app's calls (no payload)", True,
                          excerpt(relay_log, 0, r"/v1/(devices|auth|relay|pairs|push)", 12)))
    return results


CHECKS = {"health": check_health, "forward": check_forward, "push": push_checks.check_push, "android": check_android}


def run_checks(layout: Layout, names: list[str], wait_s: float) -> int:
    if not layout.json_path.exists():
        raise StackError(f"no stack in {layout.root}: run `up` first")
    info = json.loads(layout.json_path.read_text())
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        raise StackError(f"unknown check(s): {', '.join(unknown)}; choose from {', '.join(CHECKS)}")
    results = []
    for name in names:
        print(f"== {name}", flush=True)
        try:
            results += CHECKS[name](layout, info, wait_s)
        except (OSError, StackError, subprocess.SubprocessError, KeyError, ValueError, IndexError) as error:
            results.append(Result(f"{name} check", False, [f"{type(error).__name__}: {error}"]))
    return summarize(results)


def print_captures(layout: Layout, provider: str, prk: str | None, k_push: str | None, since_ms: int) -> int:
    info = json.loads(layout.json_path.read_text())
    key = bytes.fromhex(k_push) if k_push else push_crypto.push_key(bytes.fromhex(prk)) if prk else None
    for c in read_captures(Path(info[provider]["capture"]), since_ms):
        stamp = time.strftime("%H:%M:%S", time.localtime(c["ts"] / 1000))
        if c["provider"] == "apns":
            body, h = c.get("body") or {}, c.get("headers") or {}
            line = (f"{stamp} APNs {c['endpoint']} {c['status']} reason={((body.get('aps') or {}).get('alert') or {}).get('loc-key')} "
                    f"collapse={h.get('apns-collapse-id')} expiration={h.get('apns-expiration')} "
                    f"level={(body.get('aps') or {}).get('interruption-level')} pair={body.get('p')} "
                    f"token_ok={c['provider_token'].get('valid')}")
            if key and body.get("hl"):
                try:
                    line += f" hl={push_crypto.summary(*push_crypto.open_hl(key, body['hl']))}"
                except ValueError as error:
                    line += f" hl=({error})"
        elif c["provider"] == "fcm":
            message = (c.get("body") or {}).get("message") or {}
            line = f"{stamp} FCM {c['status']} data={message.get('data')} android={message.get('android')}"
        else:
            line = f"{stamp} FCM OAuth {c['status']} assertion_ok={c['assertion'].get('valid')}"
        print(line)
    return 0
