"""Check push-envelope.json and relay-frame.json independently of the generator.

- K_push: HKDF with hashlib/hmac (verify_common), chained to the PRK of pair-prk.json.
- Envelopes: decoded as I-NSE does (strict standard base64 → UTF-8 JSON → AAD rebuilt from the parsed fields) and
  decrypted two ways (libsodium, and HChaCha20 + ChaCha20-Poly1305 as on Apple); every negative vector must fail for
  its stated reason and only for it.
- HR frames: parsed with struct, the inner frame compared with hl-frame.json and decrypted with its stream key; the
  text rewrite is checked with a small top-level JSON scanner that keeps the raw text of env.
"""
import base64
import binascii
import json
import re
import struct

from verify_common import H, b64_decode_strict, hkdf, uuid16, uuid_str, xchacha_open_both, xchacha_seal_apple

PUSH_INFO = b"handlive/v1/push"
DAY_MS = 86_400_000
PUSH_REASONS = {"wrong_key", "tag_mismatch", "aad_mismatch", "stale", "not_b64"}
FRAME_REASONS = {"bad_magic", "unsupported_version", "unknown_op", "truncated"}
TEXT_REASONS = {"bad_wrapper": "BAD_REQUEST", "not_paired": "NOT_PAIRED"}
UUID_V8 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
REASON_OF_TYPE = {("sms", "new"): "sms_new", ("call_event", "state"): "call_incoming"}
TTL = {"sms_new": 86_400, "call_incoming": 30}


def k_push(prk: bytes) -> bytes:
    return hkdf(prk, PUSH_INFO, 32)


def open_push(key: bytes, env_b64: str, aad_override: bytes | None = None):
    """I-NSE: hl → envelope JSON → decrypt. Returns (envelope dict, (sodium, apple)) or raises on bad encoding."""
    wire = b64_decode_strict(env_b64).decode("utf-8")
    env = json.loads(wire)
    raw = b64_decode_strict(env["payload"])
    aad = aad_override or f"{env['v']}|{env['type']}|{env['id']}|{env['ts']}".encode()
    return env, xchacha_open_both(key, raw[:24], aad, raw[24:-16], raw[-16:])


def _check_key(c, n: str, v: dict, pair_prk: dict) -> None:
    pv = pair_prk[v["pair_name"]]
    c.eq(f"{n} PRK and pair_id from pair-prk.json", (v["prk_source"], v["prk"], v["pair_id"]),
         ("pair-prk.json", pv["prk"], pv["pair_id"]))
    c.eq(f"{n} K_push", (v["salt"], v["info"], v["length"], v["k_push"]),
         ("", PUSH_INFO.decode(), 32, k_push(H(v["prk"])).hex()))


def _check_envelope(c, n: str, v: dict, keys: dict, pair_prk: dict) -> None:
    pv = pair_prk[v["pair_name"]]
    c.eq(f"{n} K_push of its pair", v["k_push"], keys[v["pair_name"]])
    c.eq(f"{n} devices of the pair", (v["pair_id"], v["sender_device_id"], v["recipient_device_id"]),
         (pv["pair_id"], pv["android_device_id"], pv["client_device_id"]))
    c.eq(f"{n} env_b64 = b64(UTF-8 envelope)", b64_decode_strict(v["env_b64"]).decode(), v["envelope"])
    env, (sodium, apple) = open_push(H(v["k_push"]), v["env_b64"])
    c.eq(f"{n} envelope fields in order", list(env.items()),
         [("v", 1), ("type", v["type"]), ("id", v["id"]), ("ts", v["ts"]), ("payload", v["payload_b64"])])
    aad = f"1|{v['type']}|{v['id']}|{v['ts']}"
    c.eq(f"{n} AAD", (v["aad"], v["aad_hex"]), (aad, aad.encode().hex()))
    raw = b64_decode_strict(env["payload"])
    c.eq(f"{n} payload split", (raw[:24].hex(), raw[24:-16].hex(), raw[-16:].hex()), (v["nonce"], v["ciphertext"], v["tag"]))
    pt = v["plaintext"].encode()
    c.eq(f"{n} decrypted two ways", (sodium, apple), (pt, pt))
    c.eq(f"{n} Apple-style encryption", xchacha_seal_apple(H(v["k_push"]), raw[:24], pt, aad.encode()), raw[24:])
    body = json.loads(pt)
    reason = REASON_OF_TYPE.get((v["type"], body["op"]))
    c.eq(f"{n} push reason of the message", v["reason"], reason)
    if body["op"] == "new":
        c.true(f"{n} push envelope carries no local_id", "local_id" not in body["data"]["message"])
    req = json.loads(v["push_request"])
    collapse = (f"sms:{body['data']['message']['message_key']}" if v["type"] == "sms"
                else f"call:{body['data']['call_id']}")
    c.eq(f"{n} POST /v1/push body", req, {"pair_id": v["pair_id"], "to": v["recipient_device_id"], "kind": "alert",
                                         "reason": reason, "env_b64": v["env_b64"], "collapse_key": collapse,
                                         "ttl_s": TTL[reason]})
    c.true(f"{n} env_b64 ≤ 3,000 characters", len(v["env_b64"]) <= 3000)
    apns = json.loads(v["apns_payload"])
    thread = f"sms:{body['data']['thread']['thread_id']}" if v["type"] == "sms" else "calls"
    level = "time-sensitive" if reason == "call_incoming" else "active"
    c.eq(f"{n} APNs payload", apns, {"aps": {"alert": {"loc-key": f"push.{reason}"}, "mutable-content": 1,
                                             "sound": "default", "thread-id": thread, "interruption-level": level},
                                     "p": v["pair_id"], "hl": v["env_b64"]})
    c.true(f"{n} APNs payload ≤ 4 KB", len(v["apns_payload"].encode()) <= 4096)
    c.eq(f"{n} APNs headers", v["apns_headers"], {"apns-push-type": "alert", "apns-topic": "app.handlive.ios",
                                                  "apns-priority": "10", "apns-collapse-id": collapse})


def _check_push_negative(c, n: str, v: dict, keys_by_pair_id: dict) -> None:
    right = H(keys_by_pair_id[v["pair_id"]])
    key = H(v["key"])
    reason = v["reason"]
    c.true(f"{n} known reason", reason in PUSH_REASONS)
    if reason == "not_b64":
        try:
            base64.b64decode(v["env_b64"], validate=True)
            decoded = True
        except (binascii.Error, ValueError):
            decoded = False
        c.true(f"{n} strict standard base64 refuses it", not decoded)
        c.true(f"{n} it is the base64url form of a real envelope",
               json.loads(base64.urlsafe_b64decode(v["env_b64"] + "=" * (-len(v["env_b64"]) % 4)))["v"] == 1)
        return
    env, (sodium, apple) = open_push(key, v["env_b64"])
    if reason == "stale":
        c.eq(f"{n} decrypts", (sodium is not None, apple is not None), (True, True))
        c.true(f"{n} older than 24 h when received", v["received_at_ms"] - env["ts"] > DAY_MS)
        return
    c.eq(f"{n} refused", (sodium, apple), (None, None))
    if reason == "wrong_key":
        c.true(f"{n} the key is not K_push", key != right)
        c.true(f"{n} K_push opens it", open_push(right, v["env_b64"])[1][0] is not None)
    elif reason == "tag_mismatch":
        c.eq(f"{n} with K_push", key, right)
    elif reason == "aad_mismatch":
        c.eq(f"{n} with K_push", key, right)
        if "aad_used" in v:
            c.true(f"{n} opens with the wrong AAD it was sealed with",
                   open_push(key, v["env_b64"], v["aad_used"].encode())[1][0] is not None)


def check_push_envelope(c, doc, all_docs) -> None:
    pair_prk = {p["name"]: p for p in all_docs["pair-prk.json"]["vectors"]}
    keys, kinds = {}, []
    for v in doc["vectors"]:
        kinds.append(v["kind"])
        if v["kind"] == "key":
            _check_key(c, f"push-envelope/{v['name']}", v, pair_prk)
            keys[v["pair_name"]] = k_push(H(pair_prk[v["pair_name"]]["prk"])).hex()
    for v in doc["vectors"]:
        if v["kind"] == "envelope":
            _check_envelope(c, f"push-envelope/{v['name']}", v, keys, pair_prk)
    c.true("push-envelope: K_push for every pair of pair-prk.json", set(keys) == set(pair_prk))
    c.true("push-envelope: sms and call_event envelopes",
           {v["type"] for v in doc["vectors"] if v["kind"] == "envelope"} == {"sms", "call_event"})
    by_id = {p["pair_id"]: keys[name] for name, p in pair_prk.items()}
    for v in doc["invalid_vectors"]:
        _check_push_negative(c, f"push-envelope/{v['name']}", v, by_id)
    c.true("push-envelope: every negative reason is covered",
           {v["reason"] for v in doc["invalid_vectors"]} == PUSH_REASONS)


def parse_hr(frame: bytes):
    """Returns (ver, op, device_id, inner) or the reason the relay refuses the frame. The relay checks only the
    header and that an HL frame follows; the HL frame itself is the receiving device's business (0.5.2)."""
    if len(frame) < 20:
        return "truncated"
    if frame[:2] != b"HR":
        return "bad_magic"
    ver, op = struct.unpack_from(">BB", frame, 2)
    if ver != 1:
        return "unsupported_version"
    if op != 1:
        return "unknown_op"
    inner = frame[20:]
    if not inner:
        return "truncated"
    return ver, op, uuid_str(frame[4:20]), inner


def top_level_raw(text: str) -> dict:
    """Raw text of each top-level value of a JSON object, keys in order; ValueError when it is not an object."""
    decoder, i, out = json.JSONDecoder(), 0, {}
    ws = re.compile(r"\s*")
    i = ws.match(text, i).end()
    if text[i:i + 1] != "{":
        raise ValueError("not an object")
    i = ws.match(text, i + 1).end()
    while text[i:i + 1] != "}":
        key, i = decoder.raw_decode(text, i)
        i = ws.match(text, i).end()
        if text[i:i + 1] != ":":
            raise ValueError("expected ':'")
        i = ws.match(text, i + 1).end()
        _, end = decoder.raw_decode(text, i)
        if key in out:
            raise ValueError(f"repeated {key}")
        out[key] = text[i:end]
        i = ws.match(text, end).end()
        if text[i:i + 1] == ",":
            i = ws.match(text, i + 1).end()
        elif text[i:i + 1] != "}":
            raise ValueError("expected ',' or '}'")
    if text[i + 1:].strip():
        raise ValueError("text after the object")
    return out


def relay_text(sender: str, outbound: str, peers: set):
    """What the relay answers to a text wrapper: the inbound text, or the relay error code."""
    try:
        raw = top_level_raw(outbound)
    except ValueError:
        return "BAD_REQUEST"
    if not {"to", "env"} <= set(raw):  # other fields (a "from" included) are ignored, 0.5.1 rule 6
        return "BAD_REQUEST"
    to = json.loads(raw["to"])
    env = json.loads(raw["env"])
    if not (isinstance(to, str) and UUID_V8.match(to)) or not isinstance(env, dict):
        return "BAD_REQUEST"
    if to not in peers or to == sender:
        return "NOT_PAIRED"
    return '{"from":' + json.dumps(sender) + ',"env":' + raw["env"] + "}"


def check_relay_frame(c, doc, all_docs) -> None:
    hl = {v["name"]: v for v in all_docs["hl-frame.json"]["vectors"]}
    p1 = all_docs["pair-prk.json"]["vectors"][0]
    mac, phone = p1["client_device_id"], p1["android_device_id"]
    frames = {}
    for v in doc["vectors"]:
        n = f"relay-frame/{v['name']}"
        if v["kind"] == "frame":
            frame = H(v["frame"])
            parsed = parse_hr(frame)
            c.true(f"{n} parses", isinstance(parsed, tuple))
            if not isinstance(parsed, tuple):
                continue
            ver, op, device_id, inner = parsed
            c.eq(f"{n} fields", (v["magic"], v["ver"], v["op"], v["op_name"], v["device_id"], v["device_id_hex"],
                                 v["header"], v["inner"], v["length"]),
                 ("4852", ver, op, "forward", device_id, uuid16(device_id).hex(), frame[:20].hex(), inner.hex(),
                  len(frame)))
            src = hl[v["inner_source"].removeprefix("hl-frame.json / ")]
            c.eq(f"{n} inner frame is an HL frame", (inner[:3], len(inner) >= 11 + 24 + 16), (b"HL\x01", True))
            c.eq(f"{n} inner frame intact", v["inner"], src["frame"])
            n12 = H(src["frame"])
            sodium, apple = xchacha_open_both(H(src["key"]), n12[11:35], n12[:11], n12[35:-16], n12[-16:])
            c.eq(f"{n} inner frame still decrypts", (sodium, apple), (H(src["plaintext"]), H(src["plaintext"])))
            sender, recipient = (mac, phone) if src["direction"] == "c2s" else (phone, mac)
            outbound = v["direction"] == "device_to_relay"
            c.eq(f"{n} device_id is the {'destination' if outbound else 'source'} of the inner frame", device_id,
                 recipient if outbound else sender)
            frames[v["frame"]] = parsed
        elif v["kind"] == "rewrite":
            out, inb = frames[v["outbound"]], frames[v["inbound"]]
            c.eq(f"{n} outbound names the recipient, inbound the sender", (out[2], inb[2]),
                 (v["recipient_device_id"], v["sender_device_id"]))
            c.eq(f"{n} only the device_id changes", (H(v["outbound"])[:4], out[3]), (H(v["inbound"])[:4], inb[3]))
        elif v["kind"] == "text_rewrite":
            got = relay_text(v["sender_device_id"], v["outbound"], {phone, mac} - {v["sender_device_id"]})
            c.eq(f"{n} inbound text", got, v["inbound"])
            c.eq(f"{n} env kept byte for byte", top_level_raw(v["inbound"])["env"], v["env"])
            c.eq(f"{n} env is an envelope", list(json.loads(v["env"])), ["v", "type", "id", "ts", "payload"])
            if "spoofed_from" in v:
                c.true(f"{n} the device's from is not kept", json.loads(v["inbound"])["from"] != v["spoofed_from"])
    kinds = {v["kind"] for v in doc["vectors"]}
    c.true("relay-frame: frame, rewrite and text_rewrite vectors", kinds == {"frame", "rewrite", "text_rewrite"})
    c.true("relay-frame: a spoofed from is covered", any("spoofed_from" in v for v in doc["vectors"]))
    for v in doc["invalid_vectors"]:
        n = f"relay-frame/{v['name']}"
        if v["kind"] == "frame":
            c.eq(f"{n} refused for its reason", parse_hr(H(v["frame"])), v["reason"])
            c.eq(f"{n} relay error", v["expected_error"], "BAD_REQUEST")
        else:
            got = relay_text(v["sender_device_id"], v["outbound"], {phone, mac} - {v["sender_device_id"]})
            c.eq(f"{n} relay error", (got, TEXT_REASONS[v["reason"]]), (v["expected_error"], v["expected_error"]))
    c.true("relay-frame: every frame reason is covered",
           {v["reason"] for v in doc["invalid_vectors"] if v["kind"] == "frame"} == FRAME_REASONS)


CHECKS = {"push-envelope.json": check_push_envelope, "relay-frame.json": check_relay_frame}
