"""Kiểm ed25519.json và relay-auth.json bằng libsodium (pynacl), độc lập với phía sinh (`cryptography`).

Vector âm được kiểm theo đúng lý do ghi trong `reason`: bị từ chối, và từ chối vì đúng chỗ đó (ví dụ chữ ký
của vector `device_id_mismatch` vẫn hợp lệ, chỉ phép kiểm device_id bắt được).
"""
import json
import struct

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from verify_common import H, b64u, b64u_decode, uuid16
from verify_session_checks import device_id

L = 2**252 + 27742317777372353535851937790883648493
REGISTER_FIELDS = ["device_id", "platform", "app_version", "ik_sig_pub", "ts", "sig"]
AUTH_FIELDS = ["device_id", "challenge", "sig"]


def verifies(pub: bytes, message: bytes, sig: bytes) -> bool:
    """Kiểm chặt của libsodium: chữ ký 64 byte, S < L, điểm hợp lệ."""
    if len(sig) != 64:
        return False
    try:
        VerifyKey(pub).verify(message, sig)
        return True
    except (BadSignatureError, ValueError):
        return False


def _reduced(sig: bytes) -> bytes:
    return sig[:32] + (int.from_bytes(sig[32:], "little") % L).to_bytes(32, "little")


def check_ed25519(c, doc):
    for v in doc["vectors"]:
        n = f"ed25519/{v['name']}"
        seed, pub, msg, sig = H(v["seed"]), H(v["public_key"]), H(v["message"]), H(v["signature"])
        key = SigningKey(seed)
        c.eq(f"{n} public_key từ seed", bytes(key.verify_key), pub)
        c.eq(f"{n} chữ ký tất định", key.sign(msg).signature, sig)
        c.true(f"{n} chữ ký hợp lệ", verifies(pub, msg, sig))
    c.eq("ed25519 có RFC 8032 TEST 1–3", sorted(v["name"] for v in doc["vectors"]),
         [f"RFC 8032 7.1 TEST {i}" for i in (1, 2, 3)])
    valid = [(H(v["public_key"]), H(v["message"]), H(v["signature"])) for v in doc["vectors"]]
    for v in doc["invalid_vectors"]:
        n = f"ed25519/{v['name']}"
        pub, msg, sig = H(v["public_key"]), H(v["message"]), H(v["signature"])
        c.eq(f"{n} phải bị từ chối", verifies(pub, msg, sig), False)
        reason = v["reason"]
        if reason == "signature_length":
            c.true(f"{n} độ dài khác 64", len(sig) != 64)
        elif reason == "signature_not_canonical":
            c.true(f"{n} S ≥ L", int.from_bytes(sig[32:], "little") >= L)
            c.true(f"{n} S mod L thì hợp lệ", verifies(pub, msg, _reduced(sig)))
        elif reason == "wrong_key":
            c.true(f"{n} hợp lệ với khóa khác", any(m == msg and s == sig and p != pub for p, m, s in valid))
        elif reason == "message_tampered":
            c.true(f"{n} chữ ký thuộc thông điệp khác", any(p == pub and s == sig and m != msg for p, m, s in valid))
        elif reason == "signature_mismatch":
            c.true(f"{n} chữ ký bị sửa", any(p == pub and m == msg and s != sig for p, m, s in valid))
        else:
            c.true(f"{n} reason {reason!r} không nằm trong tập đã định", False)


def _request(c, n, v, fields):
    req = json.loads(v["request"])
    c.eq(f"{n} request đúng thứ tự trường", list(req), fields)
    c.eq(f"{n} request dạng gọn", json.dumps(req, separators=(",", ":"), ensure_ascii=False), v["request"])
    return req


def relay_decision(v) -> str | None:
    """Relay xử lý request của vector âm: trả chỗ từ chối, None nếu (sai) chấp nhận."""
    req = json.loads(v["request"])
    sig = b64u_decode(req["sig"])
    if len(sig) != 64:
        return "signature_length"
    pub = H(v["ik_sig_pub"])
    if v["kind"] == "register":
        if b64u_decode(req["ik_sig_pub"]) != pub:
            return "key_mismatch"
        if device_id(pub) != req["device_id"]:
            return "device_id_mismatch"
        msg = b"HLREG1" + uuid16(req["device_id"]) + pub + req["platform"].encode() + struct.pack(">q", req["ts"])
    else:
        if b64u_decode(req["challenge"]) != H(v["challenge"]):
            return "challenge_mismatch"
        msg = b"HLAUTH1" + H(v["challenge"]) + uuid16(req["device_id"])
    return None if verifies(pub, msg, sig) else "signature_invalid"


def check_relay_auth(c, doc, all_docs):
    ids = {v["ik_sig_pub"]: v["device_id"] for v in all_docs["device-id.json"]["vectors"]}
    kinds = set()
    for v in doc["vectors"]:
        n = f"relay-auth/{v['name']}"
        seed, pub, did = H(v["ik_sig_seed"]), H(v["ik_sig_pub"]), v["device_id"]
        key = SigningKey(seed)
        c.eq(f"{n} ik_sig_pub từ seed", bytes(key.verify_key), pub)
        c.eq(f"{n} device_id từ khóa", device_id(pub), did)
        c.eq(f"{n} device_id khớp device-id.json", ids.get(v["ik_sig_pub"]), did)
        if v["kind"] == "register":
            msg = b"HLREG1" + uuid16(did) + pub + v["platform"].encode() + struct.pack(">q", v["ts"])
            req = _request(c, n, v, REGISTER_FIELDS)
            c.eq(f"{n} request", (req["device_id"], req["platform"], req["app_version"], b64u_decode(req["ik_sig_pub"]),
                                  req["ts"], req["sig"]),
                 (did, v["platform"], v["app_version"], pub, v["ts"], b64u(H(v["sig"]))))
        else:
            chal = H(v["challenge"])
            c.eq(f"{n} challenge 32 byte", len(chal), 32)
            c.eq(f"{n} challenge_b64u", (b64u(chal), b64u_decode(v["challenge_b64u"])), (v["challenge_b64u"], chal))
            msg = b"HLAUTH1" + chal + uuid16(did)
            req = _request(c, n, v, AUTH_FIELDS)
            c.eq(f"{n} request", (req["device_id"], req["challenge"], req["sig"]),
                 (did, v["challenge_b64u"], b64u(H(v["sig"]))))
        c.eq(f"{n} message", msg.hex(), v["message"])
        c.eq(f"{n} chữ ký tất định", key.sign(msg).signature.hex(), v["sig"])
        c.true(f"{n} chữ ký hợp lệ", verifies(pub, msg, H(v["sig"])))
        c.eq(f"{n} relay chấp nhận", relay_decision({**v, "request": v["request"]}), None)
        kinds.add((v["ik_sig_pub"], v["kind"]))
    c.eq("relay-auth: mỗi khóa có cả register và auth", len(kinds), 2 * len({k for k, _ in kinds}))
    reasons = set()
    for v in doc["invalid_vectors"]:
        n = f"relay-auth/{v['name']}"
        decision, reason = relay_decision(v), v["reason"]
        reasons.add(reason)
        c.true(f"{n} phải bị từ chối", decision is not None)
        req = json.loads(v["request"])
        sig = b64u_decode(req["sig"])
        if reason == "signature_length":
            c.eq(f"{n} từ chối vì độ dài", decision, "signature_length")
        elif reason == "device_id_mismatch":
            c.eq(f"{n} từ chối vì device_id", decision, "device_id_mismatch")
            c.true(f"{n} chữ ký tự nó hợp lệ", verifies(H(v["ik_sig_pub"]), H(v["signed_message"]), sig))
        elif reason in ("message_tampered", "wrong_label"):
            c.eq(f"{n} từ chối vì chữ ký", decision, "signature_invalid")
            c.true(f"{n} chữ ký hợp lệ với thông điệp đã ký", verifies(H(v["ik_sig_pub"]), H(v["signed_message"]), sig))
            if reason == "wrong_label":
                label = b"HLAUTH1" if v["kind"] == "register" else b"HLREG1"
                c.true(f"{n} thông điệp đã ký mang nhãn kia", H(v["signed_message"]).startswith(label))
        elif reason == "wrong_key":
            c.eq(f"{n} từ chối vì chữ ký", decision, "signature_invalid")
            c.true(f"{n} khóa ký khác khóa đã lưu", v["signer_pub"] != v["ik_sig_pub"])
        elif reason == "signature_not_canonical":
            c.eq(f"{n} từ chối vì chữ ký", decision, "signature_invalid")
            c.true(f"{n} S ≥ L", int.from_bytes(sig[32:], "little") >= L)
            c.true(f"{n} S mod L thì hợp lệ", verifies(H(v["ik_sig_pub"]), H(v["signed_message"]), _reduced(sig)))
        else:
            c.true(f"{n} reason {reason!r} không nằm trong tập đã định", False)
    c.eq("relay-auth: đủ loại vector âm", reasons,
         {"message_tampered", "device_id_mismatch", "wrong_label", "wrong_key", "signature_length",
          "signature_not_canonical"})


CHECKS = {"ed25519.json": check_ed25519, "relay-auth.json": check_relay_auth}
