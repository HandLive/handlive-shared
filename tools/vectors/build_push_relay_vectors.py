"""Build push-envelope.json and relay-frame.json.

push-envelope.json (00-common-specs 0.4.4, 0.5.1, 0.6.1; CONN-04 step 5b and API 2–4; SMS-02 API 2; CALL-01 API 4):
- kind "key": K_push = HKDF-SHA256(PRK, empty salt, info "handlive/v1/push", L = 32) for both pairs of pair-prk.json.
- kind "envelope": what the phone sends for an iPhone/iPad without a session: an envelope built as over a session
  but encrypted with K_push (nonce 24 bytes, AAD "<v>|<type>|<id>|<ts>" as in 0.5.1), its env_b64 (standard base64
  of the UTF-8 envelope JSON), the POST /v1/push body, and the APNs payload and headers the relay derives from it.
- invalid_vectors: what I-NSE must refuse — another key, a tampered tag, a wrong AAD, an envelope older than 24 h,
  an env_b64 that is not standard base64.

relay-frame.json (00-common-specs 0.4.3; CONN-03 API 6):
- kind "frame": the binary routing frame "HR" ‖ ver 0x01 ‖ op 0x01 (forward) ‖ device_id (16 bytes: destination
  from a device, source towards a device) ‖ the intact HL frame (inner frames from hl-frame.json).
- kind "rewrite": the relay replaces the destination device_id by the sender's and changes nothing else.
- kind "text_rewrite": the text wrapper {"to", "env"} becomes {"from", "env"} with env byte for byte as received; a
  "from" sent by the device is ignored like any unknown field (0.5.1 rule 6) and never trusted.
- invalid_vectors: frames and wrappers the relay must refuse. The relay checks only the 20-byte HR header and that an
  HL frame follows; it never inspects the HL frame itself (the receiving device does, 0.5.2).

Generator side: `cryptography` HKDF and pynacl XChaCha20-Poly1305 through handlive_protocol_derivations.
"""
import base64
import json
import struct

from handlive_protocol_derivations import (b64, compact_json, envelope_aad, envelope_wire, hkdf, test_bytes,
                                           uuid_bytes, xchacha_seal)

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
PUSH_INFO = "handlive/v1/push"
DAY_MS = 86_400_000
IOS_TOPIC = "app.handlive.ios"

SMS_NEW_VI = {"op": "new", "data": {
    "message": {"message_key": "sms:12847", "thread_id": 42, "address": "+84900000123", "body": "Nhớ mang theo tài liệu",
                "box": "inbox", "ts": 1727150060456, "ts_sent": 1727150059000, "read": False, "sub_id": 1},
    "thread": {"thread_id": 42, "addresses": ["+84900000123"], "display_name": "Nguyễn Văn A",
               "snippet": "Nhớ mang theo tài liệu", "last_ts": 1727150060456, "unread_count": 2}}}
SMS_NEW_SHORT_CODE = {"op": "new", "data": {
    "message": {"message_key": "sms:12850", "thread_id": 57, "address": "VIETTEL",
                "body": "Your data plan has been renewed until 26/10.", "box": "inbox", "ts": 1727150070000,
                "ts_sent": None, "read": False, "sub_id": None},
    "thread": {"thread_id": 57, "addresses": ["VIETTEL"], "display_name": None,
               "snippet": "Your data plan has been renewed until 26/10.", "last_ts": 1727150070000,
               "unread_count": 1}}}
CALL_RINGING = {"op": "state", "data": {
    "call_id": "0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90", "direction": "incoming", "state": "ringing", "waiting": False,
    "number": "+84900000123", "display_name": "Nguyễn Văn A", "presentation": "allowed", "sub_id": 1,
    "sim_label": "SIM 1", "waiting_number": None, "waiting_display_name": None, "started_at": 1727150400123,
    "answered_at": None, "ended_at": None, "end_reason": None,
    "controls": {"answer": True, "reject": True, "end": False, "hold": "unavailable", "dtmf": "unavailable",
                 "mute": "unavailable"},
    "hfp_connected": False, "audio_on": "phone"}}
# (name, envelope type, id, ts, plaintext, push reason, collapse_key, ttl_s, APNs thread-id)
ENVELOPES = [
    ("pair 2 / sms/new (Vietnamese content)", "sms", "0192f3e4-7a10-7b20-8c30-9d40ae50bf60", 1727150060500,
     SMS_NEW_VI, "sms_new", "sms:12847", 86_400, "sms"),
    ("pair 2 / sms/new from a sender name, no contact, no SIM", "sms", "0192f3e4-7c31-7d42-9e53-af64b075c186",
     1727150070050, SMS_NEW_SHORT_CODE, "sms_new", "sms:12850", 86_400, "sms"),
    ("pair 2 / call_event/state ringing", "call_event", "0192f3f0-6a2c-7d3e-9f40-5a6b7c8d9eaf", 1727150400400,
     CALL_RINGING, "call_incoming", "call:0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90", 30, "calls"),
]
INTERRUPTION = {"sms_new": "active", "call_incoming": "time-sensitive", "call_missed": "active"}


def push_key(prk: bytes) -> bytes:
    """0.6.1: K_push = HKDF(PRK, info "handlive/v1/push"); no salt stated → empty, no L stated → 32 (0.6.3 step 8)."""
    return hkdf(prk, PUSH_INFO.encode(), 32)


def seal_envelope(key: bytes, typ: str, env_id: str, ts: int, plaintext: bytes, aad: str | None = None) -> dict:
    aad = aad or envelope_aad(1, typ, env_id, ts)
    nonce = test_bytes(f"push nonce {env_id}", 24)
    ct, tag = xchacha_seal(key, nonce, plaintext, aad.encode())
    wire = envelope_wire(1, typ, env_id, ts, b64(nonce + ct + tag))
    return {"aad": aad, "nonce": nonce, "ciphertext": ct, "tag": tag, "payload_b64": b64(nonce + ct + tag),
            "envelope": wire, "env_b64": b64(wire.encode())}


def _key_vector(pv: dict) -> dict:
    return {"name": f"{pv['name'].replace('cặp', 'pair')} / K_push", "kind": "key", "pair_name": pv["name"],
            "pair_id": pv["pair_id"],
            "prk_source": "pair-prk.json", "prk": pv["prk"], "salt": "", "info": PUSH_INFO, "length": 32,
            "k_push": push_key(H(pv["prk"])).hex()}


def _envelope_vector(pv: dict, name, typ, env_id, ts, body, reason, collapse_key, ttl_s, thread_id) -> dict:
    key = push_key(H(pv["prk"]))
    plaintext = compact_json(body)
    sealed = seal_envelope(key, typ, env_id, ts, plaintext.encode())
    request = {"pair_id": pv["pair_id"], "to": pv["client_device_id"], "kind": "alert", "reason": reason,
               "env_b64": sealed["env_b64"], "collapse_key": collapse_key, "ttl_s": ttl_s}
    apns = {"aps": {"alert": {"loc-key": f"push.{reason}"}, "mutable-content": 1, "sound": "default",
                    "thread-id": thread_id, "interruption-level": INTERRUPTION[reason]},
            "p": pv["pair_id"], "hl": sealed["env_b64"]}
    assert len(sealed["env_b64"]) <= 3000 and len(compact_json(apns).encode()) <= 4096, name
    return {"name": name, "kind": "envelope", "pair_name": pv["name"], "pair_id": pv["pair_id"],
            "sender_device_id": pv["android_device_id"], "recipient_device_id": pv["client_device_id"],
            "k_push": key.hex(), "v": 1, "type": typ, "id": env_id, "ts": ts, "aad": sealed["aad"],
            "aad_hex": sealed["aad"].encode().hex(), "plaintext": plaintext, "nonce": sealed["nonce"].hex(),
            "ciphertext": sealed["ciphertext"].hex(), "tag": sealed["tag"].hex(), "payload_b64": sealed["payload_b64"],
            "envelope": sealed["envelope"], "env_b64": sealed["env_b64"], "reason": reason,
            "push_request": compact_json(request), "apns_payload": compact_json(apns),
            "apns_headers": {"apns-push-type": "alert", "apns-topic": IOS_TOPIC, "apns-priority": "10",
                             "apns-collapse-id": collapse_key}}


def _push_negatives(pairs: dict, v: dict) -> list[dict]:
    p1, p2 = H(pairs["cặp 1"]["prk"]), H(pairs["cặp 2"]["prk"])
    right = push_key(p2)
    body = v["plaintext"].encode()
    env = json.loads(v["envelope"])
    raw = bytearray(base64.b64decode(env["payload"]))
    raw[-1] ^= 0x01
    tampered = compact_json({**env, "payload": b64(bytes(raw))})
    spaced_aad = f"1 | {v['type']} | {v['id']} | {v['ts']}"
    spaced = seal_envelope(right, v["type"], v["id"], v["ts"], body, aad=spaced_aad)
    url_form = base64.urlsafe_b64encode(v["envelope"].encode()).decode().rstrip("=")
    assert url_form != v["env_b64"]
    base = v["name"]
    out = [
        ("K_push of pair 1", "wrong_key", push_key(p1), v["env_b64"], {}),
        ("PRK used directly instead of K_push", "wrong_key", p2, v["env_b64"], {}),
        ("K_disc (info handlive/v1/discovery) instead of K_push", "wrong_key",
         hkdf(p2, b"handlive/v1/discovery", 32), v["env_b64"], {}),
        ("tag flipped", "tag_mismatch", right, b64(tampered.encode()), {}),
        ("ts changed after encryption (AAD)", "aad_mismatch", right,
         b64(compact_json({**env, "ts": env["ts"] + 1}).encode()), {}),
        ("type changed to call_event after encryption (AAD)", "aad_mismatch", right,
         b64(compact_json({**env, "type": "call_event"}).encode()), {}),
        ("encrypted with the AAD written with spaces", "aad_mismatch", right, spaced["env_b64"],
         {"aad_used": spaced_aad}),
        ("received more than 24 h after ts", "stale", right, v["env_b64"],
         {"received_at_ms": v["ts"] + DAY_MS + 1}),
        ("env_b64 written in base64url without padding", "not_b64", right, url_form, {}),
    ]
    return [{"name": f"{base} / {n}", "reason": r, "pair_id": v["pair_id"], "key": k.hex(), "env_b64": e, **extra}
            for n, r, k, e, extra in out]


def push_file(ctx) -> dict:
    pairs = {p["name"]: p for p in ctx["pairs"]}
    target = pairs["cặp 2"]  # the client of pair 2 is the iPhone of relay-auth.json (RFC 8032 TEST 3)
    envelopes = [_envelope_vector(target, *spec) for spec in ENVELOPES]
    return {"description": "Push to an iPhone/iPad without a session: K_push = HKDF-SHA256(PRK, empty salt, info "
                           "\"handlive/v1/push\", L = 32); the envelope is built as over a session and encrypted with "
                           "K_push exactly as 0.5.1 (payload = b64(nonce(24) ‖ ciphertext ‖ tag(16)), AAD = UTF-8 "
                           "\"<v>|<type>|<id>|<ts>\"); env_b64 = standard base64 (with padding) of the UTF-8 envelope "
                           "JSON, sent as env_b64 of POST /v1/push and as hl of the APNs payload. I-NSE derives K_push "
                           "from the PRK of pair p, decodes hl, rebuilds the AAD from the parsed envelope and "
                           "decrypts. APNs thread-id is the generic sms or calls; collapse_key is the message_key of "
                           "an SMS, call:<call_id> for a call.",
            "source": f"{SPEC} 0.4.4, 0.5.1, 0.6.1; 03-connectivity.md CONN-04 step 5b, API 2, API 4; 05-sms.md SMS-02 "
                      "API 2; 06-call-control.md CALL-01 API 4; PRK from pair-prk.json",
            "vectors": [_key_vector(p) for p in ctx["pairs"]] + envelopes,
            "invalid_vectors": _push_negatives(pairs, envelopes[0])}


def hr_frame(device_id: str, inner: bytes, ver: int = 1, op: int = 1) -> bytes:
    """0.4.3: "HR" ‖ ver (1) ‖ op (1, 0x01 forward) ‖ device_id (16) ‖ intact HL frame."""
    return b"HR" + bytes([ver, op]) + uuid_bytes(device_id) + inner


def _frame_vector(name, direction, device_id, inner_name, inner: bytes) -> dict:
    frame = hr_frame(device_id, inner)
    return {"name": name, "kind": "frame", "direction": direction, "magic": "4852", "ver": 1, "op": 1,
            "op_name": "forward", "device_id": device_id, "device_id_hex": uuid_bytes(device_id).hex(),
            "header": frame[:20].hex(), "inner_source": f"hl-frame.json / {inner_name}", "inner": inner.hex(),
            "frame": frame.hex(), "length": len(frame)}


def _text_rewrite(name, sender, recipient, env_text: str, outbound: str) -> dict:
    assert json.loads(outbound)["to"] == recipient
    return {"name": name, "kind": "text_rewrite", "sender_device_id": sender, "recipient_device_id": recipient,
            "env": env_text, "outbound": outbound,
            "inbound": '{"from":' + json.dumps(sender) + ',"env":' + env_text + "}"}


def relay_file(ctx, hl_doc: dict, envelope_doc: dict) -> dict:
    p1 = ctx["pairs"][0]
    mac, phone = p1["client_device_id"], p1["android_device_id"]
    inner = {v["name"]: H(v["frame"]) for v in hl_doc["vectors"]}
    up, down = "call-audio Mac→Android seq 1", "call-audio Android→Mac seq 0"
    frames = [
        _frame_vector("Mac → relay: call-audio frame for the phone", "device_to_relay", phone, up, inner[up]),
        _frame_vector("relay → phone: the same frame from the Mac", "relay_to_device", mac, up, inner[up]),
        _frame_vector("phone → relay: call-audio frame for the Mac", "device_to_relay", mac, down, inner[down]),
        _frame_vector("relay → Mac: the same frame from the phone", "relay_to_device", phone, down, inner[down]),
    ]
    rewrites = [{"name": f"rewrite: {a['name']} ⇒ {b['name']}", "kind": "rewrite", "sender_device_id": s,
                 "recipient_device_id": r, "outbound": a["frame"], "inbound": b["frame"]}
                for a, b, s, r in ((frames[0], frames[1], mac, phone), (frames[2], frames[3], phone, mac))]
    env = json.loads(next(v["envelope"] for v in envelope_doc["vectors"] if v["name"] == "sms send Mac→Android"))
    env_text = compact_json(env)
    spaced_env = json.dumps(env, indent=1)
    texts = [
        _text_rewrite("text wrapper Mac → phone (compact)", mac, phone, env_text,
                      '{"to":' + json.dumps(phone) + ',"env":' + env_text + "}"),
        _text_rewrite("text wrapper with env first, spaces and an indented env", mac, phone, spaced_env,
                      '{ "env" : ' + spaced_env + ' , "to" : ' + json.dumps(phone) + " }"),
        {**_text_rewrite("a from sent by the device is ignored and replaced by the sender", mac, phone, env_text,
                         '{"to":' + json.dumps(phone) + ',"from":' + json.dumps(phone) + ',"env":' + env_text + "}"),
         "spoofed_from": phone},
    ]
    good = H(frames[0]["frame"])
    neg_frames = [
        ("magic HL instead of HR", "bad_magic", b"HL" + good[2:]),
        ("version 0x02", "unsupported_version", good[:2] + b"\x02" + good[3:]),
        ("op 0x02", "unknown_op", good[:3] + b"\x02" + good[4:]),
        ("header cut to 19 bytes", "truncated", good[:19]),
        ("header only, no HL frame", "truncated", good[:20]),
    ]
    negatives = [{"name": n, "reason": r, "kind": "frame", "frame": f.hex(), "expected_error": "BAD_REQUEST"}
                 for n, r, f in neg_frames]
    neg_texts = [
        ("to is not a device_id", "bad_wrapper", "BAD_REQUEST", '{"to":"phone","env":' + env_text + "}"),
        ("wrapper without env", "bad_wrapper", "BAD_REQUEST", '{"to":' + json.dumps(phone) + "}"),
        ("to is the sender itself", "not_paired", "NOT_PAIRED", '{"to":' + json.dumps(mac) + ',"env":' + env_text + "}"),
    ]
    negatives += [{"name": n, "reason": r, "kind": "text", "sender_device_id": mac, "outbound": t,
                   "expected_error": e} for n, r, e, t in neg_texts]
    return {"description": "Relay routing: binary frame \"HR\" (0x48 0x52) ‖ ver 0x01 ‖ op 0x01 (forward) ‖ device_id "
                           "(16 bytes: the destination in a frame a device sends, the source in a frame the relay "
                           "delivers) ‖ the HL frame, intact. The relay only swaps the device_id; text frames "
                           "{\"to\", \"env\"} become {\"from\", \"env\"} with env byte for byte as received, and a "
                           "from sent by the device is ignored. The relay checks only the HR header and that an HL "
                           "frame follows, never the HL frame itself. Invalid vectors: what the relay refuses, with "
                           "the relay error it answers.",
            "source": f"{SPEC} 0.4.3, 0.5.2; 03-connectivity.md CONN-03 API 6; inner frames from hl-frame.json, "
                      "device_ids of pair 1 (pair-prk.json), env from envelope.json",
            "vectors": frames + rewrites + texts, "invalid_vectors": negatives}


def build(ctx, message_files: dict) -> dict:
    return {"push-envelope.json": push_file(ctx),
            "relay-frame.json": relay_file(ctx, message_files["hl-frame.json"], message_files["envelope.json"])}
