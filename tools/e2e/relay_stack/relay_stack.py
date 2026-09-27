"""The HandLive relay with everything it needs, on this machine: PostgreSQL, Redis, the relay (migrations applied at
start), a TLS front with a test certificate for the Android emulator, and mock APNs and FCM servers that record every
push the relay sends (README.md).

    tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py up [--state-dir DIR] [--build]
    tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py status [--json]
    tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py check [health forward push android] [--wait-s N]
    tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py captures [--provider apns|fcm] [--prk HEX]
    tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py down [--wipe]

`up` prints the endpoints, the SPKI pin for the Android build and the capture files, and writes them to
<state-dir>/relay_stack.json. A fresh RELAY_JWT_SECRET is generated at every start and kept only in the relay's
environment.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import local_keys  # noqa: E402
import stack_processes as proc  # noqa: E402
from stack_config import APNS_TOPIC, RELAY_DIR, Layout, default_state_dir, describe, load_layout, save_ports  # noqa: E402

PYTHON = sys.executable
SERVICES = ("tls-front", "relay", "mock-fcm", "mock-apns", "redis")  # stop order; postgres last


def relay_binary(build: bool) -> Path:
    binary = RELAY_DIR / "target" / "debug" / "relay-server"
    if build or not binary.exists():
        cargo = shutil.which("cargo") or "/opt/homebrew/opt/rustup/bin/cargo"
        print(f"building relay-server in {RELAY_DIR} …", flush=True)
        env = {**os.environ, "PATH": f"/opt/homebrew/opt/rustup/bin:{os.environ.get('PATH', '')}"}
        result = subprocess.run([cargo, "build", "-p", "relay-server"], cwd=RELAY_DIR, env=env, timeout=1200,
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise proc.StackError(f"cargo build failed:\n{result.stderr[-2000:]}")
    return binary


def relay_env(layout: Layout, apns_p8: Path, fcm_account: Path) -> dict:
    p = layout.ports
    return {
        "DATABASE_URL": layout.database_url,
        "REDIS_URL": f"redis://127.0.0.1:{p.redis}",
        "RELAY_JWT_SECRET": secrets.token_urlsafe(48),  # fresh per start, never written to disk
        "RELAY_BIND": f"127.0.0.1:{p.relay}",
        "RELAY_TRUSTED_PROXIES": "127.0.0.1",
        "RELAY_INSTANCE_ID": "e2e-local",
        "RELAY_APNS_KEY_PATH": str(apns_p8),
        "RELAY_APNS_KEY_ID": local_keys.APNS_KEY_ID,
        "RELAY_APNS_TEAM_ID": local_keys.APNS_TEAM_ID,
        "RELAY_APNS_TOPIC": APNS_TOPIC,
        "RELAY_APNS_URL": f"http://127.0.0.1:{p.apns}",
        "RELAY_APNS_SANDBOX_URL": f"http://127.0.0.1:{p.apns}/sandbox",
        "RELAY_FCM_PROJECT_ID": local_keys.FCM_PROJECT,
        "RELAY_FCM_SERVICE_ACCOUNT_PATH": str(fcm_account),
        "RELAY_FCM_URL": f"http://127.0.0.1:{p.fcm}",
        "RUST_LOG": "info",
    }


def up(args) -> int:
    layout = load_layout(args.state_dir, {"postgres": args.pg_port, "redis": args.redis_port,
                                          "relay": args.relay_port, "tls": args.tls_port, "apns": args.apns_port,
                                          "fcm": args.fcm_port})
    layout.dirs()
    save_ports(layout)
    p = layout.ports
    running = {name: proc.recorded(layout, name) for name in SERVICES}
    pg_up = (layout.pg_data / "PG_VERSION").exists() and proc.pg_running(layout)
    if any(running.values()) or pg_up:
        raise proc.StackError(f"the stack in {layout.root} is already running; `status` or `down` first")
    busy = [f"{name} {port}" for name, port in vars(p).items() if proc.port_open(port)]
    if busy:
        raise proc.StackError(f"ports in use: {', '.join(busy)} (pick others with --*-port on a new --state-dir)")
    tls = local_keys.tls_files(layout.tls)
    apns_p8, apns_pub = local_keys.apns_key(layout.keys)
    fcm_account, fcm_pub = local_keys.fcm_account(layout.keys, f"http://127.0.0.1:{p.fcm}/token")
    binary = relay_binary(args.build)
    pids = {}
    try:
        proc.pg_init(layout)
        proc.pg_start(layout)
        pids["redis"] = proc.redis_start(layout)
        proc.wait_port(p.redis, 15, "redis", pids["redis"])
        pids["mock-apns"] = proc.spawn(layout, "mock-apns", [
            PYTHON, str(HERE / "mock_apns.py"), "--port", str(p.apns), "--public-key", str(apns_pub),
            "--key-id", local_keys.APNS_KEY_ID, "--team-id", local_keys.APNS_TEAM_ID,
            "--capture", str(layout.captures / "apns.jsonl")], marker=f"mock_apns.py --port {p.apns}")
        pids["mock-fcm"] = proc.spawn(layout, "mock-fcm", [
            PYTHON, str(HERE / "mock_fcm.py"), "--port", str(p.fcm), "--public-key", str(fcm_pub),
            "--project", local_keys.FCM_PROJECT, "--client-email", local_keys.FCM_CLIENT_EMAIL,
            "--capture", str(layout.captures / "fcm.jsonl")], marker=f"mock_fcm.py --port {p.fcm}")
        proc.wait_port(p.apns, 15, "mock APNs", pids["mock-apns"])
        proc.wait_port(p.fcm, 15, "mock FCM", pids["mock-fcm"])
        relay_log = layout.logs / "relay.log"
        start_mark = relay_log.stat().st_size if relay_log.exists() else 0
        pids["relay"] = proc.spawn(layout, "relay", [str(binary)], marker=str(binary),
                                   env=relay_env(layout, apns_p8, fcm_account))
        wait_log_from(relay_log, start_mark, "migrations applied; listening on", 60, pids["relay"])
        proc.wait_port(p.relay, 30, "relay", pids["relay"])
        pids["tls-front"] = proc.spawn(layout, "tls-front", [
            PYTHON, str(HERE / "tls_front.py"), "--listen", f"127.0.0.1:{p.tls}", "--upstream",
            f"127.0.0.1:{p.relay}", "--cert", str(tls.chain), "--key", str(tls.key),
            "--log", str(layout.logs / "tls-front.log")], marker=f"tls_front.py --listen 127.0.0.1:{p.tls}")
        proc.wait_port(p.tls, 15, "TLS front", pids["tls-front"])
    except (proc.StackError, OSError, subprocess.SubprocessError) as error:
        print(f"start failed: {error}", file=sys.stderr)
        down_all(layout)
        return 1
    info = describe(layout, tls, local_keys.APNS_KEY_ID, local_keys.APNS_TEAM_ID, local_keys.FCM_PROJECT,
                    {**pids, "postgres": "pg_ctl -D " + str(layout.pg_data)})
    info["started_at"] = int(time.time() * 1000)
    layout.json_path.write_text(json.dumps(info, indent=1) + "\n")
    print_status(info, layout)
    return 0


def wait_log_from(path: Path, offset: int, text: str, timeout_s: float, pid: int) -> None:
    """wait_log on the part of `path` written after `offset` (the log is appended across starts)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            with path.open("rb") as f:
                f.seek(offset)
                if text.encode() in f.read():
                    return
        if not proc.alive(pid):
            with path.open("rb") as f:
                f.seek(offset)
                tail = f.read().decode(errors="replace")[-1500:]
            raise proc.StackError(f"the relay exited during start-up:\n{tail}")
        time.sleep(0.2)
    raise proc.StackError(f"no '{text}' in {path} after {timeout_s:.0f} s")


def down_all(layout: Layout) -> list[str]:
    out = [proc.stop(layout, name) for name in SERVICES]
    if (layout.pg_data / "PG_VERSION").exists():
        out.append(proc.pg_stop(layout))
    return out


def down(args) -> int:
    layout = load_layout(args.state_dir)
    for line in down_all(layout):
        print(line)
    if args.wipe:
        for sub in ("postgres", "redis", "captures", "logs", "run", "relay_stack.json"):
            target = layout.root / sub
            shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
        print(f"wiped the data, logs and captures in {layout.root} (keys kept for the pinned APK)")
    return 0


def print_status(info: dict, layout: Layout) -> None:
    r, t, a, f = info["relay"], info["tls"], info["apns"], info["fcm"]
    print(f"relay stack in {info['state_dir']}")
    print(f"  relay          {r['http']} (plain, trusts X-Forwarded-For from {r['trusted_proxies']})")
    print(f"  TLS front      {r['https']}  ·  from the emulator {r['emulator_https']}  ·  WS {r['wss']}")
    print(f"  CA cert        {t['ca_cert']}  (Python clients: SSL_CERT_FILE={t['ca_cert']})")
    print(f"  SPKI pin       {t['spki_pin']}  (CA; server certificate {t['server_spki_pin']})")
    print(f"  Android build  {' '.join(info['android_build']['gradle_args'])}")
    print(f"  mock APNs      {a['url']} (sandbox {a['sandbox_url']}), topic {a['topic']}, capture {a['capture']}")
    print(f"  mock FCM       {f['url']} (project {f['project_id']}), capture {f['capture']}")
    print(f"  PostgreSQL     {info['postgres']['url']}")
    print(f"  Redis          {info['redis']['url']}")
    print(f"  logs           {layout.logs}")
    print(f"  JSON           {layout.json_path}")


def status(args) -> int:
    layout = load_layout(args.state_dir)
    if not layout.json_path.exists():
        print(f"no stack in {layout.root} (run `up`)")
        return 1
    info = json.loads(layout.json_path.read_text())
    states = {name: proc.recorded(layout, name) for name in SERVICES}
    states["postgres"] = proc.pg_running(layout)
    if args.json:
        print(json.dumps({**info, "running": {k: bool(v) for k, v in states.items()}}, indent=1))
    else:
        print_status(info, layout)
        print("  processes      " + ", ".join(f"{k} {'up' if v else 'DOWN'}" for k, v in states.items()))
    return 0 if all(states.values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("up", "down", "status", "check", "captures"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--state-dir", type=Path, default=default_state_dir())
        if name == "up":
            cmd.add_argument("--build", action="store_true", help="cargo build the relay first")
            for port in ("pg", "redis", "relay", "tls", "apns", "fcm"):
                cmd.add_argument(f"--{port}-port", type=int, help="only on the first up of a state dir")
        elif name == "down":
            cmd.add_argument("--wipe", action="store_true", help="also delete the data, logs and captures")
        elif name == "status":
            cmd.add_argument("--json", action="store_true")
        elif name == "check":
            cmd.add_argument("checks", nargs="*", default=["health", "forward", "push"],
                             help="health, forward, push, android (default: the first three)")
            cmd.add_argument("--wait-s", type=float, default=0, help="android: wait this long for the app")
        elif name == "captures":
            cmd.add_argument("--provider", choices=("apns", "fcm"), default="apns")
            cmd.add_argument("--prk", help="hex PRK of the pair: decrypts each hl with its K_push")
            cmd.add_argument("--k-push", help="hex K_push instead of the PRK")
            cmd.add_argument("--since-ms", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "up":
            return up(args)
        if args.command == "down":
            return down(args)
        if args.command == "status":
            return status(args)
        import stack_checks  # the checks import the bench and vector tools
        if args.command == "check":
            return stack_checks.run_checks(load_layout(args.state_dir), args.checks, args.wait_s)
        return stack_checks.print_captures(load_layout(args.state_dir), args.provider, args.prk, args.k_push,
                                           args.since_ms)
    except proc.StackError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
