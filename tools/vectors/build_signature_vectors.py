"""Dựng vector chữ ký Ed25519: ed25519.json và relay-auth.json.

- ed25519.json: RFC 8032 §7.1 TEST 1–3 (chữ ký attestation của PAIR-01 và chữ ký gửi relay dùng cùng
  thuật toán) và vector âm mà mọi bên kiểm phải từ chối, kể cả S không chính tắc (S ≥ L).
- relay-auth.json: chữ ký đăng ký thiết bị "HLREG1" (CONN-03 API 1) và xác thực "HLAUTH1" (0.6.4, CONN-03
  API 3) bằng khóa RFC 8032 TEST 1–3; vector âm là các request relay phải từ chối.
Phía sinh ký bằng `cryptography`; verify_signature_checks.py kiểm lại bằng libsodium (pynacl).
"""
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

import rfc_source_values as R
from handlive_protocol_derivations import (auth_message, b64u, compact_json, device_id_from_pub, ed25519_pub,
                                           ed25519_sign, registration_message, test_bytes)

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
# (chỉ số khóa RFC 8032, platform, app_version, ts đăng ký, nhãn test_bytes của challenge)
DEVICES = [
    (0, "macos", "1.0.0 (100)", 1727151100000, "relay challenge 1"),
    (1, "android", "1.0.0 (100)", 1727151200000, "relay challenge 2"),
    (2, "ios", "1.0.0 (100)", 1727151300000, "relay challenge 3"),
]


def _rejected_by_cryptography(pub: bytes, message: bytes, sig: bytes) -> bool:
    if len(sig) != 64:
        return True
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(pub).verify(sig, message)
        return False
    except InvalidSignature:
        return True


def _flip(data: bytes, index: int, mask: int) -> bytes:
    out = bytearray(data)
    out[index] ^= mask
    return bytes(out)


def _s_plus_l(sig: bytes) -> bytes:
    """Cùng chữ ký nhưng S thay bằng S + L (vẫn vừa 32 byte little endian) — dạng không chính tắc."""
    s = int.from_bytes(sig[32:], "little") + R.ED25519_L
    assert s < 2**256
    return sig[:32] + s.to_bytes(32, "little")


def ed25519_file() -> dict:
    vs = []
    for (name, seed, pub), (name2, msg, sig) in zip(R.ED25519_8032, R.ED25519_8032_SIG):
        assert name == name2 and ed25519_pub(H(seed)).hex() == pub
        assert ed25519_sign(H(seed), H(msg)).hex() == sig, f"{name}: chữ ký RFC không tái tạo được"
        vs.append({"name": name, "seed": seed, "public_key": pub, "message": msg, "signature": sig})
    t1, t2, t3 = vs
    neg = [
        {"name": "TEST 2 / thông điệp sửa 1 bit", "reason": "message_tampered", "public_key": t2["public_key"],
         "message": _flip(H(t2["message"]), 0, 0x01).hex(), "signature": t2["signature"]},
        {"name": "TEST 1 / R sửa 1 bit", "reason": "signature_mismatch", "public_key": t1["public_key"],
         "message": t1["message"], "signature": _flip(H(t1["signature"]), 0, 0x01).hex()},
        {"name": "TEST 3 / S sửa 1 bit", "reason": "signature_mismatch", "public_key": t3["public_key"],
         "message": t3["message"], "signature": _flip(H(t3["signature"]), 32, 0x01).hex()},
        {"name": "TEST 3 / kiểm bằng khóa TEST 1", "reason": "wrong_key", "public_key": t1["public_key"],
         "message": t3["message"], "signature": t3["signature"]},
        {"name": "TEST 1 / S + L (không chính tắc)", "reason": "signature_not_canonical",
         "public_key": t1["public_key"], "message": t1["message"], "signature": _s_plus_l(H(t1["signature"])).hex()},
        {"name": "TEST 2 / chữ ký 63 byte", "reason": "signature_length", "public_key": t2["public_key"],
         "message": t2["message"], "signature": t2["signature"][:126]},
    ]
    for v in neg:
        assert _rejected_by_cryptography(H(v["public_key"]), H(v["message"]), H(v["signature"])), v["name"]
    return {"description": "Ed25519 (RFC 8032, PureEdDSA): signature = Ed25519(seed, message), 64 byte R ‖ S. "
                           "Cùng thuật toán với chữ ký attestation (PAIR-01) và HLREG1/HLAUTH1 (relay-auth.json). "
                           "Bên kiểm phải từ chối mọi invalid_vectors, kể cả S không chính tắc (S ≥ L, RFC 8032 §5.1.7) "
                           "và chữ ký sai độ dài.",
            "source": "RFC 8032 §7.1 TEST 1–3; vector âm tự dựng từ ba test đó", "vectors": vs,
            "invalid_vectors": neg}


def _register_request(did: str, platform: str, app_version: str, pub: bytes, ts: int, sig: bytes) -> str:
    return compact_json({"device_id": did, "platform": platform, "app_version": app_version,
                         "ik_sig_pub": b64u(pub), "ts": ts, "sig": b64u(sig)})


def _auth_request(did: str, challenge: bytes, sig: bytes) -> str:
    return compact_json({"device_id": did, "challenge": b64u(challenge), "sig": b64u(sig)})


def relay_auth_file() -> dict:
    vs, dev = [], []
    for key_index, platform, app_version, ts, chal_label in DEVICES:
        name, seed_hex, pub_hex = R.ED25519_8032[key_index]
        seed, pub = H(seed_hex), H(pub_hex)
        did = device_id_from_pub(pub)
        test_no = name.rsplit(" ", 1)[1]
        reg_msg = registration_message(did, pub, platform, ts)
        reg_sig = ed25519_sign(seed, reg_msg)
        vs.append({"name": f"HLREG1 {platform} (khóa TEST {test_no})", "kind": "register", "ik_sig_seed": seed_hex,
                   "ik_sig_pub": pub_hex, "device_id": did, "platform": platform, "app_version": app_version,
                   "ts": ts, "message": reg_msg.hex(), "sig": reg_sig.hex(),
                   "request": _register_request(did, platform, app_version, pub, ts, reg_sig)})
        challenge = test_bytes(chal_label, 32)
        auth_msg = auth_message(challenge, did)
        auth_sig = ed25519_sign(seed, auth_msg)
        vs.append({"name": f"HLAUTH1 {platform} (khóa TEST {test_no})", "kind": "auth", "ik_sig_seed": seed_hex,
                   "ik_sig_pub": pub_hex, "device_id": did, "challenge": challenge.hex(),
                   "challenge_b64u": b64u(challenge), "message": auth_msg.hex(), "sig": auth_sig.hex(),
                   "request": _auth_request(did, challenge, auth_sig)})
        dev.append((seed, pub, did, platform, app_version, ts, challenge))
    return {"description": "Chữ ký Ed25519 của thiết bị gửi relay. Đăng ký (POST /v1/devices): message = \"HLREG1\" ‖ "
                           "device_id (16 byte) ‖ ik_sig_pub (32) ‖ UTF-8(platform) ‖ ts (int64 BE). Lấy token "
                           "(POST /v1/auth/token): message = \"HLAUTH1\" ‖ challenge (32 byte thô, đã giải b64u) ‖ "
                           "device_id (16). sig = Ed25519(ik_sig, message). request = body JSON trên dây (b64u không "
                           "padding). Relay kiểm device_id = UUIDv8(SHA-256(ik_sig_pub)) (0.2) rồi chữ ký theo luật chặt "
                           "(S < L); mọi invalid_vectors phải bị từ chối: 400 BAD_REQUEST khi sig không phải b64u 64 "
                           "byte, còn lại 401 SIGNATURE_INVALID. Với kind = auth, ik_sig_pub là khóa relay lưu cho "
                           "device_id và challenge là giá trị relay đã cấp.",
            "source": f"{SPEC} 0.6.4; 03-connectivity.md CONN-03 API 1, API 3; khóa RFC 8032 §7.1 TEST 1–3",
            "vectors": vs, "invalid_vectors": _relay_negatives(dev)}


def _relay_negatives(dev) -> list[dict]:
    (s1, p1, d1, pf1, av1, ts1, c1), (s2, p2, d2, _pf2, _av2, _ts2, c2), (s3, p3, d3, _pf3, _av3, _ts3, _c3) = dev
    neg = []

    def reg(name, reason, pub, request, signed_message=None, signer_pub=None):
        v = {"name": name, "kind": "register", "reason": reason, "ik_sig_pub": pub.hex(), "request": request}
        if signed_message is not None:
            v["signed_message"] = signed_message.hex()
        if signer_pub is not None:
            v["signer_pub"] = signer_pub.hex()
        neg.append(v)

    def auth(name, reason, pub, challenge, request, signed_message=None, signer_pub=None):
        v = {"name": name, "kind": "auth", "reason": reason, "ik_sig_pub": pub.hex(), "challenge": challenge.hex(),
             "request": request}
        if signed_message is not None:
            v["signed_message"] = signed_message.hex()
        if signer_pub is not None:
            v["signer_pub"] = signer_pub.hex()
        neg.append(v)

    m = registration_message(d1, p1, pf1, ts1)
    sig = ed25519_sign(s1, m)
    reg("HLREG1 / ts đổi sau khi ký", "message_tampered", p1, _register_request(d1, pf1, av1, p1, ts1 + 1, sig), m)
    reg("HLREG1 / platform đổi sau khi ký", "message_tampered", p1, _register_request(d1, "ios", av1, p1, ts1, sig), m)
    m = registration_message(d2, p1, pf1, ts1)
    reg("HLREG1 / device_id không dẫn xuất từ ik_sig_pub", "device_id_mismatch", p1,
        _register_request(d2, pf1, av1, p1, ts1, ed25519_sign(s1, m)), m)
    m = b"HLAUTH1" + registration_message(d1, p1, pf1, ts1)[6:]
    reg("HLREG1 / ký với nhãn HLAUTH1", "wrong_label", p1, _register_request(d1, pf1, av1, p1, ts1, ed25519_sign(s1, m)), m)
    m = registration_message(d1, p1, pf1, ts1)
    reg("HLREG1 / ký bằng khóa khác", "wrong_key", p1, _register_request(d1, pf1, av1, p1, ts1, ed25519_sign(s2, m)),
        signer_pub=p2)

    m = auth_message(c1, d1)
    sig = ed25519_sign(s1, m)
    other = test_bytes("relay challenge khác", 32)
    auth("HLAUTH1 / challenge khác giá trị đã ký", "message_tampered", p1, other, _auth_request(d1, other, sig), m)
    m = auth_message(c2, d3)
    auth("HLAUTH1 / ký thay thiết bị khác", "wrong_key", p3, c2, _auth_request(d3, c2, ed25519_sign(s2, m)),
         signer_pub=p2)
    m = b"HLREG1" + auth_message(c1, d1)[7:]
    auth("HLAUTH1 / ký với nhãn HLREG1", "wrong_label", p1, c1, _auth_request(d1, c1, ed25519_sign(s1, m)), m)
    m = auth_message(c2, d2)
    sig = ed25519_sign(s2, m)
    auth("HLAUTH1 / sig 63 byte", "signature_length", p2, c2, _auth_request(d2, c2, sig[:63]))
    auth("HLAUTH1 / S + L (không chính tắc)", "signature_not_canonical", p2, c2, _auth_request(d2, c2, _s_plus_l(sig)),
         m)
    return neg


def build() -> dict:
    return {"ed25519.json": ed25519_file(), "relay-auth.json": relay_auth_file()}
