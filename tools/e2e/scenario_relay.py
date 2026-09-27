"""Scenarios `relay` and `push`: the phone's traffic through the local relay stack (relay_stack/, CONN-03, CONN-04).

`relay`: the fake Mac registers with the relay, pairs on the LAN, both sides register the pair, then the LAN goes
away (the forward is removed and the session dropped without session/bye). The phone must come to the relay (CONN-03
step 2), and a ringing call, its answer and a new SMS must reach the Mac through `/v1/relay`.

`push`: a fake iPhone registers an APNs token, pairs, says goodbye (as iOS does in the background) and stays off.
An incoming SMS and an incoming call must make the phone call `POST /v1/push` (`sms_new`, `call_incoming`, then
`call_missed`); the mock APNs records what Apple would receive, and `hl` must open with the pair's K_push.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import mac_crypto as C
from fake_mac import FakeClient
from relay_client import RelayAccount, RelayLink, RelayStack, error_code
from scenario_calls import CALL_PERMISSIONS, CONTACT_NAME, _action, _wait_state
from scenario_common import FAKE, grant_and_refresh
from scenario_setup import _pair_known, ensure_paired
from scenario_sms import SMS_PERMISSIONS


def _stack(ctx) -> RelayStack | None:
    path = Path(ctx.args.relay_state or os.environ.get("HANDLIVE_RELAY_STACK_DIR")
                or Path(os.environ.get("TMPDIR", "/tmp")) / "handlive-relay-stack")
    try:
        return RelayStack.load(path)
    except (OSError, KeyError, ValueError) as exc:
        ctx.rec.check("the local relay stack is up (relay_stack.json)", "relay_stack", False, f"{path}: {exc}")
        return None


def _register(ctx, account: RelayAccount, who: str) -> bool:
    status, body = account.register()
    return ctx.rec.check(f"{who} registers with the relay and gets a JWT (HLREG1, HLAUTH1)", "CONN-03 API 1–3, 0.6.4",
                         status == 200 and bool(account.token), f"{status} {error_code(body)}")


def _pair_on_relay(ctx, account: RelayAccount, who: str) -> None:
    """PAIR-01 step 11: the phone registers the pair right after pairing; the client's own call is then idempotent."""
    deadline = time.monotonic() + 30
    listed, status = None, 0
    while time.monotonic() < deadline:
        status, body = account.pairs()
        listed = next((p for p in body.get("pairs", []) if p.get("pair_id") == account.record.pair_id), None)
        if listed:
            break
        time.sleep(2)
    ctx.rec.check("the phone registered the new pair with the relay (GET /v1/pairs lists it, not revoked)",
                  "PAIR-01 step 11, API 8; PAIR-02 API 1", listed is not None and listed.get("revoked_at") is None,
                  json.dumps({k: listed.get(k) for k in ("peer_platform", "peer_online")}) if listed else f"{status}")
    status, body = account.register_pair()
    ctx.rec.check(f"{who} registers the same pair: 200, identical data", "PAIR-01 API 8 logic 4",
                  status == 200 if listed else status in (200, 201), f"{status} {error_code(body)}")


def _client(ctx, file: str, name: str, platform: str) -> FakeClient:
    """A client of its own for the relay stage, registered before it pairs (PAIR-01 API 8 logic 6)."""
    c = FakeClient(ctx.state_dir / file, name, platform, port=ctx.client.port,
                   bench_file=ctx.state_dir / f"hlbench-{platform}-relay.log", checker=ctx.client.checker)
    c.relay_capable = True
    if c.record.paired and not _pair_known(c):
        c.forget_pair()
    return c


def run(ctx) -> None:
    """Stage 2a: the Mac reaches the phone through the relay once the LAN is gone."""
    stack = _stack(ctx)
    if stack is None:
        return
    client = _client(ctx, "pair-macos-relay.json", "E2E Relay Mac", "macos")
    ctx.client, lan_mac = client, ctx.client
    try:
        _relay_path(ctx, stack, client)
    finally:
        ctx.disconnect()
        ctx.client = lan_mac
        ctx.adb.forward(lan_mac.port)                  # the LAN path is back for the next scenarios


def _relay_path(ctx, stack: RelayStack, client: FakeClient) -> None:
    rec, adb = ctx.rec, ctx.adb
    account = RelayAccount(stack, client.record, client.checker)
    # Registered before pairing: the phone registers the pair right after it (PAIR-01 API 8 logic 6).
    if not _register(ctx, account, client.record.name) or not ensure_paired(ctx, client):
        return
    _pair_on_relay(ctx, account, client.record.name)
    grant_and_refresh(ctx, SMS_PERMISSIONS + CALL_PERMISSIONS, "SMS and call")
    s = ctx.connect()
    if s is None:
        return
    relay_on = ((s.peer_capability or {}).get("features") or {}).get("relay", {}).get("enabled")
    rec.check("both sides have the relay on", "CONN-03 precondition 2, 0.7.2", relay_on is True)
    link = RelayLink(stack, account.token, client.checker)
    ours = lambda m: m.get("op") == "presence" and m.get("pair_id") == client.record.pair_id  # noqa: E731
    first = link.wait_control(ours, 5)
    rec.check("/v1/relay sends the presence of the pair on connect", "CONN-03 API 4, API 5", first is not None,
              f"online={first.get('online')}" if first else "no presence in 5 s")
    already = bool(first and first.get("online"))
    mark = len(link.control)
    # The client leaves the LAN: no forward any more, the session ends without session/bye (CONN-03 step 2).
    adb.forward_remove(client.port)
    t0 = time.monotonic()
    s.abort()
    ctx.session = None
    if already:
        rec.info("the phone was already on the relay (another relay pair had no session)", "CONN-03 step 2")
        online = first
    else:
        online = link.wait_control(lambda m: ours(m) and m.get("online") is True, 60, mark)
        rec.check("the phone comes to the relay after the LAN session ended without session/bye",
                  "CONN-03 step 2, API 5 (presence)", online is not None,
                  "" if online else "no presence online in 60 s",
                  latency_ms=(online["_mono"] - t0) * 1000 if online else None)
    if online is None:
        link.close()
        adb.forward(client.port)
        return
    rs = client.session(open_transport=lambda: link.channel(client.record.peer_device_id))
    try:
        rs.open()
    except Exception as exc:  # noqa: BLE001 — reported, then the LAN comes back
        rec.check("session handshake through the relay", "CONN-03 step 9", False, f"{type(exc).__name__}: {exc}")
        link.close()
        adb.forward(client.port)
        return
    ctx.session = rs
    rec.check("session handshake and capabilities through the relay", "CONN-03 step 9, CONN-01 API 4–7", True,
              latency_ms=rs.timings["total_ms"])
    _call_over_relay(ctx, rs)
    _sms_over_relay(ctx, rs)
    rec.check("no schema violation in the relayed messages and wrappers", "shared/schemas, 0.4.3",
              not rs.violations and not link.violations, "; ".join((rs.violations + link.violations)[:3]))
    errors = [m for m in link.control if m.get("op") == "error"]
    rec.check("the relay reported no error to the Mac", "CONN-03 API 5", not errors,
              "; ".join(f"{m.get('code')}" for m in errors[:3]))
    rs.close(bye=True)
    ctx.session = None
    link.close()
    adb.forward(client.port)                          # the LAN is back for the next scenarios


def _call_over_relay(ctx, s) -> None:
    rec, adb = ctx.rec, ctx.adb
    adb.delete_contacts_named(CONTACT_NAME)
    adb.insert_contact(CONTACT_NAME, FAKE["contact"])
    ctx.pause()
    mark = s.mark()
    t0 = time.monotonic()
    adb.gsm_call(FAKE["contact"].lstrip("+"))
    ring = _wait_state(s, lambda d: d["state"] == "ringing" and d["number"] == FAKE["contact"], 20, mark)
    rec.check("ringing call_event/state reaches the Mac through the relay", "CONN-03, CALL-01 (≤ 1 s via relay)",
              ring is not None and ring.data["display_name"] == CONTACT_NAME,
              "" if ring else "none in 20 s", latency_ms=(ring.mono - t0) * 1000 if ring else None, target_ms=1000)
    if ring is None:
        adb.gsm_cancel(FAKE["contact"].lstrip("+"))
        return
    call_id = ring.data["call_id"]
    ctx.pause()
    mark = s.mark()
    ack, t1 = _action(ctx, s, call_id, "answer", audio="phone")
    off = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "offhook", 10, mark)
    rec.check("answer through the relay: ack, then offhook", "CALL-02 via CONN-03",
              ack is not None and ack.ok and off is not None, f"ack={ack.ok if ack else None}",
              latency_ms=(off.mono - t1) * 1000 if off else None, target_ms=1000)
    rec.check("Android's own call state is offhook", "CALL-02 postcondition", adb.call_state().get("mCallState") == 2)
    ctx.pause()
    mark = s.mark()
    ack, t2 = _action(ctx, s, call_id, "end")
    idle = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "idle", 10, mark)
    rec.check("end through the relay: ack, then idle ended", "CALL-03 via CONN-03",
              ack is not None and ack.ok and idle is not None and idle.data["end_reason"] == "ended",
              f"ack={ack.ok if ack else None}", latency_ms=(idle.mono - t2) * 1000 if idle else None)


def _sms_over_relay(ctx, s) -> None:
    body = f"E2E relay sms {C.uuid7()[-8:]}"
    mark = s.mark()
    t0 = time.monotonic()
    ctx.adb.sms_to_phone(FAKE["sms_in"].lstrip("+"), body)
    got = s.wait(lambda m: m.type == "sms" and m.op == "new" and m.data["message"]["body"] == body, 30, after=mark)
    ctx.rec.check("incoming SMS reaches the Mac as sms/new through the relay", "SMS-02 via CONN-03 (≤ 1 s)",
                  got is not None and got.data["message"]["address"] == FAKE["sms_in"], "" if got else "none in 30 s",
                  latency_ms=(got.mono - t0) * 1000 if got else None, target_ms=1000)
    ack = s.request("sms", "sync", {"thread_limit": 20, "per_thread_limit": 5})
    ctx.rec.check("sms/sync through the relay: a page of conversations", "SMS-01 via CONN-03",
                  ack is not None and ack.ok and any(m["body"] == body for m in ack.data["messages"]),
                  f"{len(ack.data['messages'])} messages" if ack and ack.ok else f"{ack.code if ack else 'no ack'}",
                  latency_ms=ack.latency_ms if ack else None)
    local_id = C.uuid7()
    mark = s.mark()
    t1 = time.monotonic()
    ack = s.request("sms", "send", {"local_id": local_id, "addresses": [ctx.adb.console_port()],
                                    "body": f"E2E relay reply {C.uuid7()[-8:]}"})
    sent = s.wait(lambda m: m.type == "sms" and m.op == "status" and m.data["local_id"] == local_id
                  and m.data["status"] == "sent", 30, after=mark)
    ctx.rec.check("a reply through the relay: ack, then sms/status sent", "SMS-04 via CONN-03",
                  ack is not None and ack.ok and sent is not None, f"ack={ack.ok if ack else None}",
                  latency_ms=(sent.mono - t1) * 1000 if sent else None, target_ms=2000)


# ----- push path (a fake iPhone without a session) ------------------------------------------------------------------
def run_push(ctx) -> None:
    rec, adb = ctx.rec, ctx.adb
    stack = _stack(ctx)
    if stack is None:
        return
    iphone = _client(ctx, "pair-ios.json", "E2E Test iPhone", "ios")
    account = RelayAccount(stack, iphone.record, iphone.checker)
    if not _register(ctx, account, iphone.record.name):
        return
    token = os.urandom(32).hex()
    status, body = account.put_push_token(token)
    rec.check("the iPhone registers an APNs token", "CONN-04 API 1", status == 204, f"{status} {error_code(body)}")
    if not ensure_paired(ctx, iphone):
        return
    _pair_on_relay(ctx, account, iphone.record.name)
    ctx.disconnect()
    ctx.client, mac = iphone, ctx.client                # grant_and_refresh uses ctx.client's session
    try:
        grant_and_refresh(ctx, SMS_PERMISSIONS + CALL_PERMISSIONS, "SMS and call")
        s = ctx.connect()                               # capability with sms.notify, call.notify (0.7.2)
        if s is None:
            return
        time.sleep(4)                                   # like a user glancing at the app; the phone stores the
        s.close(bye=True)                               # capability asynchronously. Then iOS goes to the background
                                                        # (CONN-02 E3)
        ctx.session = None
    finally:
        ctx.client = mac
    k_push = C.push_key(bytes.fromhex(iphone.record.prk))
    adb.delete_contacts_named(CONTACT_NAME)
    adb.insert_contact(CONTACT_NAME, FAKE["contact"])
    time.sleep(2)
    _sms_push(ctx, stack, token, k_push)
    _call_push(ctx, stack, token, k_push, iphone, account)


def _captures(stack: RelayStack, token: str, since_ms: int) -> list[dict]:
    if not stack.apns_capture.exists():
        return []
    out = []
    for line in stack.apns_capture.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("device_token") == token and rec.get("ts", 0) >= since_ms:
                out.append(rec)
    return out


def _open(k_push: bytes, record: dict) -> tuple[dict, dict] | None:
    hl = (record.get("body") or {}).get("hl")
    if not hl:
        return None
    env = json.loads(base64.b64decode(hl, validate=True))
    try:
        return env, json.loads(C.open_sealed(k_push, env))
    except ValueError:
        return None


def _wait_push(stack, token, k_push, since_ms: int, pred, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for record in _captures(stack, token, since_ms):
            opened = _open(k_push, record)
            if opened and pred(opened[0], opened[1]):
                return record, opened
        time.sleep(0.5)
    return None, None


def _push_headers_ok(record: dict, collapse: str, level: str | None) -> tuple[bool, str]:
    h, aps = record.get("headers") or {}, (record.get("body") or {}).get("aps") or {}
    problems = []
    if h.get("apns-push-type") != "alert":
        problems.append(f"push-type {h.get('apns-push-type')}")
    if h.get("apns-collapse-id") != collapse:
        problems.append("collapse-id differs")
    if aps.get("mutable-content") != 1 or not (aps.get("alert") or {}).get("loc-key"):
        problems.append("no mutable-content or loc-key")
    if level and aps.get("interruption-level") != level:
        problems.append(f"interruption-level {aps.get('interruption-level')}")
    return not problems, "; ".join(problems)


def _sms_push(ctx, stack, token: str, k_push: bytes) -> None:
    rec = ctx.rec
    body = f"E2E push sms {C.uuid7()[-8:]}"
    since = C.now_ms() - 1000
    t0 = time.monotonic()
    ctx.adb.sms_to_phone(FAKE["sms_in"].lstrip("+"), body)
    record, opened = _wait_push(stack, token, k_push, since, lambda e, p: e["type"] == "sms" and p.get("op") == "new"
                                and p["data"]["message"]["body"] == body, 45)
    rec.check("incoming SMS → POST /v1/push sms_new → the mock APNs receives it", "SMS-02 step 10, CONN-04",
              record is not None, "" if record else "no APNs request for the iPhone in 45 s",
              latency_ms=(time.monotonic() - t0) * 1000 if record else None)
    if record is None:
        return
    msg = opened[1]["data"]["message"]
    rec.check("hl opens with K_push: sms/new from the fake sender, schema-valid", "0.4.4, SMS-02 API 2",
              msg["address"] == FAKE["sms_in"] and not ctx.client.checker.check_payload("sms", "new", opened[1]),
              json.dumps({"box": msg["box"], "key": msg["message_key"]}))
    ok, why = _push_headers_ok(record, msg["message_key"], None)
    rec.check("APNs request: alert, collapse-id = message_key, mutable-content, loc-key", "SMS-02 API 2, CONN-04 API 4",
              ok, why)


def _call_push(ctx, stack, token: str, k_push: bytes, iphone: FakeClient, account: RelayAccount) -> None:
    """CALL-01 step 5 and CALL-02 B1–B3: the push of a ringing call, the iPhone declining through the relay (the
    phone holds the relay while the call rings), then a second call the caller gives up → call_missed."""
    rec, adb = ctx.rec, ctx.adb
    d = _incoming_push(ctx, stack, token, k_push)
    if d is None:
        return
    t_tap = time.monotonic()                           # the user taps Decline on the notification
    link = RelayLink(stack, account.token, iphone.checker)
    online = link.wait_control(lambda m: m.get("op") == "presence" and m.get("pair_id") == iphone.record.pair_id
                               and m.get("online") is True, 20)
    rec.check("the phone is on the relay while the call rings", "CALL-01 API 4 logic 4, CONN-03 step 2",
              online is not None, "" if online else "no presence online in 20 s")
    declined = False
    if online is not None:
        s = iphone.session(open_transport=lambda: link.channel(iphone.record.peer_device_id))
        try:
            s.open()
            state = s.wait(lambda m: m.type == "call_event" and m.op == "state"
                           and m.data["call_id"] == d["call_id"], 5)
            rec.check("the relayed session gets the ringing state after capabilities", "CALL-01 E8, API 1 logic 3",
                      state is not None and state.data["state"] == "ringing")
            mark = s.mark()
            ack, _ = _action(ctx, s, d["call_id"], "reject")
            idle = s.wait(lambda m: m.type == "call_event" and m.op == "state" and m.data["call_id"] == d["call_id"]
                          and m.data["state"] == "idle", 10, after=mark)
            declined = ack is not None and ack.ok and idle is not None and idle.data["end_reason"] == "rejected"
            rec.check("Decline from the iPhone through the relay: ack, then idle rejected", "CALL-02 B1–B3, E8",
                      declined, f"ack={ack.ok if ack else None} end={idle.data['end_reason'] if idle else None}",
                      latency_ms=(time.monotonic() - t_tap) * 1000, target_ms=2000)
            answer, _ = _action(ctx, s, d["call_id"], "answer", audio="phone")
            rec.check("an iPhone may not answer → CALL_NOT_FOUND or CALL_ACTION_NOT_ALLOWED {platform}",
                      "CALL-02 E2, API 1", answer is not None and not answer.ok, f"{answer.code if answer else None}")
            rec.check("no schema violation in the iPhone's relayed session", "shared/schemas",
                      not s.violations and not link.violations, "; ".join((s.violations + link.violations)[:2]))
            s.close(bye=True)
        except Exception as exc:  # noqa: BLE001 — reported; the call is then hung up by the modem
            rec.check("the iPhone's relayed session", "CONN-03 step 9", False, f"{type(exc).__name__}: {exc}")
    link.close()
    if not declined:
        adb.gsm_cancel(FAKE["contact"].lstrip("+"))
    since = C.now_ms()
    time.sleep(8)
    missed = [r for r in _captures(stack, token, since) if (_open(k_push, r) or ({}, {}))[1].get("op") == "log_new"]
    rec.check("a declined call sends no call_missed push", "CALL-04 API 5 logic 1", not missed or not declined,
              f"{len(missed)} missed pushes")
    d = _incoming_push(ctx, stack, token, k_push)
    if d is None:
        return
    time.sleep(2)
    since = C.now_ms() - 500
    adb.gsm_cancel(FAKE["contact"].lstrip("+"))
    record, opened = _wait_push(stack, token, k_push, since, lambda e, p: e["type"] == "call_event"
                                and (p.get("op") == "log_new" or p["data"].get("end_reason") == "missed"), 30)
    rec.check("the caller hangs up → POST /v1/push call_missed", "CALL-04 step 8, API 5", record is not None,
              json.dumps({"op": opened[1]["op"]}) if opened else "no APNs request in 30 s")
    if record is not None:
        ok, why = _push_headers_ok(record, f"call:{d['call_id']}", None)
        rec.check("missed-call push replaces the incoming one (same collapse-id)", "CALL-04 API 5", ok, why)


def _incoming_push(ctx, stack, token: str, k_push: bytes) -> dict | None:
    rec, adb = ctx.rec, ctx.adb
    since = C.now_ms() - 1000
    ctx.pause()
    t0 = time.monotonic()
    adb.gsm_call(FAKE["contact"].lstrip("+"))
    record, opened = _wait_push(stack, token, k_push, since, lambda e, p: e["type"] == "call_event"
                                and p.get("op") == "state" and p["data"]["state"] == "ringing", 30)
    rec.check("ringing call → POST /v1/push call_incoming → the mock APNs receives it", "CALL-01 step 5, API 4",
              record is not None, "" if record else "no APNs request in 30 s",
              latency_ms=(time.monotonic() - t0) * 1000 if record else None)
    if record is None:
        adb.gsm_cancel(FAKE["contact"].lstrip("+"))
        return None
    d = opened[1]["data"]
    rec.check("hl opens: call_event/state ringing with the caller, iOS controls (no answer)", "CALL-01 API 1, API 4",
              d["number"] == FAKE["contact"] and d["display_name"] == CONTACT_NAME and d["controls"]["answer"] is False
              and d["controls"]["reject"] is True and not ctx.client.checker.check_payload("call_event", "state",
                                                                                          opened[1]),
              json.dumps({"presentation": d["presentation"], "controls": d["controls"]}))
    ok, why = _push_headers_ok(record, f"call:{d['call_id']}", "time-sensitive")
    rec.check("APNs request: alert, collapse-id call:<call_id>, time-sensitive", "CALL-01 API 4, CONN-04 API 4",
              ok, why)
    return d
