"""`check push`: POST /v1/push from a fake paired phone reaches the mock APNs as CONN-04 API 4 says, a wake from the
fake iPhone reaches the mock FCM as API 3 says, and a dead APNs token is forgotten (E3).

Fake devices only (app_version "0.0.0 (e2e)"), paired with a random PRK; every hl the mock captured is opened with
that pair's K_push and summarized (type, op, state), never printed with its numbers. The devices remove themselves
at the end (DELETE /v1/devices/me?revoke_pairs=false).
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import push_crypto
from capture_log import read_captures
from check_report import Result, excerpt, offset
from stack_config import APNS_TOPIC, Layout
from stack_processes import psql
from stack_rest import FakeDevice, RelayRest, error_code, fake_xff, register_pair

LEVEL = {"call_incoming": "time-sensitive", "sms_new": "active", "call_missed": "active"}
THREAD = {"call_incoming": "calls", "sms_new": "sms", "call_missed": "calls"}


def _setup(rest: RelayRest) -> tuple[dict, list[str]]:
    devices = {"phone": FakeDevice.new("android"), "iphone": FakeDevice.new("ios"), "dead": FakeDevice.new("ios")}
    problems = []
    for name, device in devices.items():
        status, reply = device.register(rest, fake_xff())
        if status != 200:
            problems.append(f"{name} registration: {status} {error_code(reply)}")
    return devices, problems


def _alert(rest, phone, to, pair_id, k_push, reason) -> dict:
    """One alert push from the phone; returns what was sent (env_b64, collapse_key, ttl_s) and the answer."""
    if reason == "call_incoming":
        call_id, body = push_crypto.fake_call_ringing()
        typ, collapse, ttl = "call_event", f"call:{call_id}", 30
    elif reason == "call_missed":
        call_id = push_crypto.uuid7()
        typ, body, collapse, ttl = "call_event", push_crypto.fake_call_missed(call_id), f"call:{call_id}", 86_400
    else:
        n = secrets.randbelow(90_000) + 10_000
        typ, body, collapse, ttl = "sms", push_crypto.fake_sms_new(n), f"sms:{n}", None  # the relay's default
    env_b64 = push_crypto.seal(k_push, typ, body)
    request = {"pair_id": pair_id, "to": to.device_id, "kind": "alert", "reason": reason, "env_b64": env_b64,
               "collapse_key": collapse, **({"ttl_s": ttl} if ttl is not None else {})}
    sent_at = time.time()
    status, reply = rest.call("POST", "/v1/push", request, token=phone.token)
    return {"reason": reason, "env_b64": env_b64, "collapse": collapse, "ttl": ttl or 86_400, "status": status,
            "code": error_code(reply), "sent_at": sent_at}


def _verify_apns(push: dict, capture: dict | None, pair_id: str, k_push: bytes, endpoint: str) -> Result:
    reason = push["reason"]
    name = f"push {reason} → mock APNs"
    if push["status"] != 202:
        return Result(name, False, [f"POST /v1/push answered {push['status']} {push['code']}"])
    if capture is None:
        return Result(name, False, ["202 from the relay, but the mock APNs captured no request with this collapse id"])
    h, body = capture["headers"], capture.get("body") or {}
    aps = body.get("aps") or {}
    expiration = int(h.get("apns-expiration", "0"))
    expected_exp = int(push["sent_at"]) + push["ttl"]
    checks = {
        "HTTP/2 to the sandbox endpoint" if endpoint == "sandbox" else "HTTP/2 to the production endpoint":
            capture["http"] == "HTTP/2" and capture["endpoint"] == endpoint,
        "ES256 provider token valid (kid, iss, iat)": capture["provider_token"].get("valid") is True,
        "apns-push-type alert, apns-priority 10": h.get("apns-push-type") == "alert" and h.get("apns-priority") == "10",
        f"apns-topic {APNS_TOPIC}": h.get("apns-topic") == APNS_TOPIC,
        f"apns-collapse-id = collapse_key {push['collapse']}": h.get("apns-collapse-id") == push["collapse"],
        f"apns-expiration = now + ttl_s {push['ttl']} (±5 s)": abs(expiration - expected_exp) <= 5,
        f"loc-key push.{reason}, no display text": aps.get("alert") == {"loc-key": f"push.{reason}"},
        f"thread-id {THREAD[reason]}, interruption-level {LEVEL[reason]}":
            aps.get("thread-id") == THREAD[reason] and aps.get("interruption-level") == LEVEL[reason],
        "mutable-content 1, sound default": aps.get("mutable-content") == 1 and aps.get("sound") == "default",
        "p = pair_id": body.get("p") == pair_id,
        "hl = env_b64 byte for byte": body.get("hl") == push["env_b64"],
        "nothing but aps, p, hl": set(body) == {"aps", "p", "hl"},
    }
    evidence = [f"{'ok ' if ok else 'BAD'} {label}" for label, ok in checks.items()]
    opened = True
    try:
        head, payload = push_crypto.open_hl(k_push, body.get("hl", ""))
        evidence.append(f"hl decrypted with the pair's K_push: {push_crypto.summary(head, payload)}")
    except (ValueError, KeyError) as error:
        opened = False
        evidence.append(f"BAD hl does not open: {error}")
    return Result(name, all(checks.values()) and opened, evidence)


def _verify_fcm(wake_answers: list, fcm: list[dict], oauth: list[dict], phone_token: str, pair_id: str) -> Result:
    sends = [c for c in fcm if ((c.get("body") or {}).get("message") or {}).get("token") == phone_token]
    evidence = [f"POST /v1/push wake user_open answered {', '.join(str(s) for s in wake_answers)}"]
    if not sends:
        return Result("push wake → mock FCM", False, evidence + ["no FCM send captured for the fake phone's token"])
    message = sends[0]["body"]["message"]
    android = message.get("android") or {}
    checks = {
        "OAuth2 JWT-bearer assertion valid (RS256, iss, scope, aud, 3600 s)":
            any(c.get("assertion", {}).get("valid") for c in oauth),
        "access token issued by the mock": sends[0].get("access_token_valid") is True,
        "data {t: wake, p: pair_id, r: user_open}": message.get("data") == {"t": "wake", "p": pair_id,
                                                                           "r": "user_open"},
        "android priority HIGH, ttl 60s, collapse_key wake":
            android == {"priority": "HIGH", "ttl": "60s", "collapse_key": "wake"},
        "no notification block, no content": "notification" not in message and set(message) == {"token", "data",
                                                                                                  "android"},
        "second wake within 5 min coalesced: 202 and one FCM send": wake_answers == [202, 202] and len(sends) == 1,
    }
    evidence += [f"{'ok ' if ok else 'BAD'} {label}" for label, ok in checks.items()]
    return Result("push wake → mock FCM", all(checks.values()), evidence)


def check_push(layout: Layout, info: dict, _wait_s: float) -> list[Result]:
    rest = RelayRest(info["relay"]["https"], info["tls"]["ca_cert"])
    apns_path, fcm_path = Path(info["apns"]["capture"]), Path(info["fcm"]["capture"])
    relay_log = Path(info["relay"]["log"])
    since, log_start = int(time.time() * 1000), offset(relay_log)
    devices, problems = _setup(rest)
    if problems:
        return [Result("push setup", False, problems)]
    phone, iphone, dead = devices["phone"], devices["iphone"], devices["dead"]
    results = []
    try:
        s1, r1, pair_id = register_pair(rest, phone, iphone)
        s2, r2, dead_pair = register_pair(rest, phone, dead)
        apns_token = "e2e0" + secrets.token_hex(30)
        fcm_token = "e2e-fcm-" + secrets.token_urlsafe(24)
        s3, _ = rest.call("PUT", "/v1/devices/me/push-token", {"provider": "apns_sandbox", "token": apns_token,
                                                              "topic": APNS_TOPIC}, token=iphone.token)
        s4, _ = rest.call("PUT", "/v1/devices/me/push-token", {"provider": "apns", "token": "dead" + secrets.token_hex(30),
                                                              "topic": APNS_TOPIC}, token=dead.token)
        s5, _ = rest.call("PUT", "/v1/devices/me/push-token", {"provider": "fcm", "token": fcm_token},
                          token=phone.token)
        setup = {"pairs": (s1, s2), "push tokens": (s3, s4, s5)}
        results.append(Result("push setup: 3 fake devices, 2 pairs, 3 push tokens",
                              (s1, s2) == (201, 201) and (s3, s4, s5) == (204, 204, 204),
                              [f"{k}: {v}" for k, v in setup.items()] + [f"pair {pair_id} (phone ↔ iPhone)"]))
        k_push = push_crypto.push_key(secrets.token_bytes(32))  # the fake pair's PRK is random and not kept
        pushes = [_alert(rest, phone, iphone, pair_id, k_push, reason)
                  for reason in ("call_incoming", "sms_new", "call_missed")]
        wakes = [rest.call("POST", "/v1/push", {"pair_id": pair_id, "to": phone.device_id, "kind": "wake",
                                                "reason": "user_open"}, token=iphone.token)[0] for _ in range(2)]
        dead_status, dead_reply = rest.call("POST", "/v1/push", {
            "pair_id": dead_pair, "to": dead.device_id, "kind": "alert", "reason": "call_incoming",
            "env_b64": push_crypto.seal(k_push, "call_event", push_crypto.fake_call_ringing()[1]),
            "collapse_key": "call:e2e-dead", "ttl_s": 30}, token=phone.token)
        time.sleep(0.3)
        apns = read_captures(apns_path, since)
        for push in pushes:
            capture = next((c for c in apns if c.get("headers", {}).get("apns-collapse-id") == push["collapse"]
                            and (c.get("body") or {}).get("p") == pair_id), None)
            results.append(_verify_apns(push, capture, pair_id, k_push, "sandbox"))
        fcm_all = read_captures(fcm_path, since)
        results.append(_verify_fcm(wakes, [c for c in fcm_all if c["provider"] == "fcm"],
                                   [c for c in fcm_all if c["provider"] == "fcm-oauth"], fcm_token, pair_id))
        token_left = psql(layout, f"SELECT push_token IS NULL FROM devices WHERE device_id = '{dead.device_id}'").strip()
        dead_captured = [c["status"] for c in apns if c.get("headers", {}).get("apns-collapse-id") == "call:e2e-dead"]
        results.append(Result("dead APNs token (410 Unregistered) → 409 PUSH_TOKEN_MISSING, token deleted (E3)",
                              dead_status == 409 and error_code(dead_reply) == "PUSH_TOKEN_MISSING"
                              and dead_captured == [410] and token_left == "t",
                              [f"relay answered {dead_status} {error_code(dead_reply)}; mock APNs answered "
                               f"{dead_captured}; push_token IS NULL = {token_left}"]))
        lines = excerpt(relay_log, log_start, r"/v1/(push|pairs|devices|auth)|apns|fcm")
        results.append(Result("relay log for these calls (path, status, bytes, time — no payload)", bool(lines),
                              lines[-14:]))
    finally:
        for device in devices.values():
            if device.token:
                rest.call("DELETE", "/v1/devices/me?revoke_pairs=false", token=device.token)
    return results
