"""Kiểm vector âm của pair-handshake.json: mỗi mục phải thất bại ĐÚNG ở phép kiểm `check` (phép kiểm đầu tiên thất
bại theo thứ tự spec của bên nhận), với mã lỗi `expected_error`, và bằng chứng kèm theo phải tái tạo đúng lỗi `reason`.
"""
import struct

from verify_common import H, b64u, b64u_decode, hkdf, hmac256, sha256, uuid16
from verify_pairing_common import (SPEC_ARGON2, Pairing, argon2id, attestation, confirm_input, done_input, read_message,
                                   transcript_parts)
from verify_signature_checks import L, verifies

CHECKED_BY = {"hello": "android", "offer": "client", "confirm": "android", "done": "client", None: "both"}
# Trường bị sửa theo phép kiểm (cho mac_mismatch / signature_mismatch).
TAMPERED_FIELD = {"offer_mac": "mac", "confirm_mac": "mac", "done_mac": "mac", "prk_check_c": "prk_check",
                  "prk_check_s": "prk_check", "sig_c": "sig", "sig_s": "sig"}
SPACED = {b"HL1|offer|": b"HL1 | offer | ", b"HL1|confirm|": b"HL1 | confirm | ", b"HL1|done|": b"HL1 | done | ",
          b"HL1|prk-check-c|": b"HL1|prk-check-s|", b"HL1|prk-check-s|": b"HL1|prk-check-c|"}
REQUIRED_REASONS = {"key_mismatch", "device_id_mismatch", "mac_mismatch", "wrong_label", "wrong_byte_order",
                    "wrong_encoding", "wrong_field_order", "message_tampered", "wrong_pin", "wrong_parameters",
                    "signature_mismatch", "signature_not_canonical"}


def _one_bit(a: bytes, b: bytes) -> bool:
    return len(a) == len(b) and sum(bin(x ^ y).count("1") for x, y in zip(a, b)) == 1


def _failure(p: Pairing, v: dict, data: dict | None) -> str | None:
    if v["message"] is not None:
        return getattr(p, f"{v['message']}_failure")(data)
    if v["check"] == "k_pin":
        return "k_pin" if H(v["k_pin_used"]) != argon2id(p.v["pin"], p.salt, SPEC_ARGON2) else None
    return "pr" if v["pr"] != sha256(p.pk)[:4].hex() else None


def _expected_error(p: Pairing, v: dict) -> str | None:
    if v["check"] == "pr":
        return None  # điện thoại không được tìm thấy (PAIR-01 E3), không có thông điệp lỗi
    if v["check"] == "k_pin" or (v["message"] == "offer" and not p.qr):
        return "PIN_INVALID"  # A5: mac của offer sai ở chế độ PIN = sai PIN
    return "AUTH_FAILED"


def _label_swapped(proof: bytes, correct: bytes, label: bytes) -> bool:
    return correct.startswith(label) and proof == SPACED[label] + correct[len(label):]


def _check_reason(c, n: str, v: dict, p: Pairing, data: dict | None) -> None:
    reason, check = v["reason"], v["check"]
    correct = {"offer_mac": p.t_offer, "confirm_mac": confirm_input(p.t_offer, p.pair_id, p.created_at,
                                                                   b64u_decode(p.confirm["sig"])),
               "done_mac": done_input(p.pair_id, b64u_decode(p.done["sig"]))}
    if reason in ("mac_mismatch", "signature_mismatch"):
        field = TAMPERED_FIELD[check]
        good = getattr(p, v["message"])[field]
        c.true(f"{n} {field} lệch đúng 1 bit so với vector dương", _one_bit(b64u_decode(data[field]), b64u_decode(good)))
    elif reason == "wrong_label" and check in correct:
        proof = H(v["mac_input"])
        c.true(f"{n} mac_input chỉ khác ở nhãn", _label_swapped(proof, correct[check], _label_of(correct[check])))
        c.eq(f"{n} mac = HMAC(K_pa, mac_input)", hmac256(p.k_pa, proof), b64u_decode(data["mac"]))
    elif reason == "wrong_label":  # prk_check với nhãn của bên kia
        proof, role = H(v["prk_check_input"]), check[-1]
        c.true(f"{n} prk_check_input dùng nhãn của bên kia",
               _label_swapped(proof, f"HL1|prk-check-{role}|".encode() + uuid16(p.pair_id), f"HL1|prk-check-{role}|".encode()))
        c.eq(f"{n} prk_check = HMAC(PRK, prk_check_input)", hmac256(p.prk, proof), b64u_decode(data["prk_check"]))
    elif reason == "wrong_byte_order":
        _check_byte_order(c, n, v, p, data)
    elif reason == "wrong_encoding":
        _check_encoding(c, n, v, p, data)
    elif reason == "wrong_field_order":
        signed = attestation(p.pair_id, p.client_id, p.android_id, p.client_pub, p.android_pub, p.created_at)
        c.eq(f"{n} signed_message đặt client trước", H(v["signed_message"]), signed)
        c.true(f"{n} sig hợp lệ trên signed_message", verifies(p.client_pub, signed, b64u_decode(data["sig"])))
    elif reason == "signature_not_canonical":
        sig = b64u_decode(data["sig"])
        s = int.from_bytes(sig[32:], "little")
        c.true(f"{n} S ≥ L", s >= L)
        c.eq(f"{n} S mod L = chữ ký của vector dương", sig[:32] + (s % L).to_bytes(32, "little"),
             b64u_decode(p.confirm["sig"]))
    elif reason == "message_tampered":
        c.true(f"{n} tls_sha256 khác chứng chỉ thật", b64u_decode(data["tls_sha256"]) != p.tls)
        c.eq(f"{n} mac là của T_offer gốc", (H(v["mac_input"]), hmac256(p.k_pa, H(v["mac_input"]))),
             (p.t_offer, b64u_decode(data["mac"])))
    elif reason == "wrong_pin":
        _check_wrong_pin(c, n, v, p, data)
    elif reason == "wrong_parameters":
        used = v["argon2_used"]
        c.eq(f"{n} tham số chỉ khác p", {k: x for k, x in used.items() if x != SPEC_ARGON2[k]}, {"p": 1})
        c.eq(f"{n} k_pin_used (argon2-cffi)", argon2id(v["pin_used"], p.salt, used).hex(), v["k_pin_used"])
        c.eq(f"{n} PIN đúng", v["pin_used"], p.v["pin"])
    elif reason == "key_mismatch":
        c.true(f"{n} ik_dh_pub khác pk", b64u_decode(data["ik_dh_pub"]) != p.pk)
    elif reason == "device_id_mismatch":
        c.true(f"{n} chỉ device_id khác", {k for k in data if data[k] != p.hello[k]} == {"device_id"})
    else:
        c.true(f"{n} reason {reason!r} không nằm trong tập đã định", False)


def _label_of(correct: bytes) -> bytes:
    """Nhãn ASCII ở đầu chuỗi đúng: "HL1|<tên>|"."""
    return correct[:correct.index(b"|", 4) + 1]


def _check_byte_order(c, n, v, p, data) -> None:
    mac = b64u_decode(data.get("mac", "")) if data and "mac" in data else None
    if v["check"] == "offer_mac" and "mac_input" in v:
        little = b"".join(b for _, b in transcript_parts(p.hello, p.offer, str_order="<"))
        c.eq(f"{n} mac_input = T_offer với độ dài str() little-endian", H(v["mac_input"]), little)
        c.eq(f"{n} mac = HMAC(K_pa, mac_input)", hmac256(p.k_pa, little), mac)
    elif v["check"] == "offer_mac":
        key = hkdf(p.secret, b"handlive/v1/pair-auth", 32, p.nonce_s + p.nonce_c)
        c.eq(f"{n} mac_key = K_pa với salt nonce_s ‖ nonce_c", H(v["mac_key"]), key)
        c.eq(f"{n} mac = HMAC(mac_key, T_offer)", hmac256(key, p.t_offer), mac)
    elif v["check"] == "confirm_mac":
        good = confirm_input(p.t_offer, p.pair_id, p.created_at, b64u_decode(p.confirm["sig"]))
        at = len(b"HL1|confirm|") + len(p.t_offer) + 16
        little = good[:at] + struct.pack("<q", p.created_at) + good[at + 8:]
        c.eq(f"{n} mac_input = created_at little-endian", H(v["mac_input"]), little)
        c.eq(f"{n} mac = HMAC(K_pa, mac_input)", hmac256(p.k_pa, little), mac)
    elif v["check"] == "prk_check_c":
        salt_in = b"".join(sorted([uuid16(p.client_id), uuid16(p.android_id)], reverse=True))
        prk = hkdf(p.dh + p.secret, b"handlive/v1/pair", 32, sha256(salt_in))
        c.eq(f"{n} PRK với salt đảo", (H(v["prk_salt_input_used"]), H(v["prk_used"])), (salt_in, prk))
        c.eq(f"{n} prk_check = HMAC(prk_used, …)", hmac256(prk, H(p.v["prk_check_c_input"])),
             b64u_decode(data["prk_check"]))
    elif v["check"] == "sig_c":
        signed = attestation(p.pair_id, p.android_id, p.client_id, p.android_pub, p.client_pub, p.created_at, "<")
        c.eq(f"{n} signed_message = attestation có created_at little-endian", H(v["signed_message"]), signed)
        c.true(f"{n} sig hợp lệ trên signed_message", verifies(p.client_pub, signed, b64u_decode(data["sig"])))
    else:
        c.true(f"{n} wrong_byte_order cho {v['check']} chưa có phép kiểm", False)


def _check_encoding(c, n, v, p, data) -> None:
    if v["check"] == "confirm_mac":
        sig = b64u_decode(p.confirm["sig"])
        options = {"sig": b"HL1|confirm|" + p.t_offer + uuid16(p.pair_id) + struct.pack(">q", p.created_at)
                   + b64u(sig).encode(),
                   "pair_id": b"HL1|confirm|" + p.t_offer + p.pair_id.encode() + struct.pack(">q", p.created_at) + sig}
        c.true(f"{n} mac_input ghép sig hoặc pair_id ở dạng chuỗi", H(v["mac_input"]) in options.values())
        c.eq(f"{n} mac = HMAC(K_pa, mac_input)", hmac256(p.k_pa, H(v["mac_input"])), b64u_decode(data["mac"]))
    elif v["check"] == "k_pin":
        c.eq(f"{n} pin_used = PIN mất số 0 đầu", v["pin_used"], str(int(p.v["pin"])))
        c.true(f"{n} PIN đúng có số 0 đầu", p.v["pin"].startswith("0"))
        c.eq(f"{n} k_pin_used (argon2-cffi)", argon2id(v["pin_used"], p.salt, SPEC_ARGON2).hex(), v["k_pin_used"])
    elif v["check"] == "pr":
        c.eq(f"{n} pr_input = chuỗi b64u của pk", H(v["pr_input"]), b64u(p.pk).encode())
        c.eq(f"{n} pr = SHA-256(pr_input)", v["pr"], sha256(H(v["pr_input"]))[:4].hex())
    else:
        c.true(f"{n} wrong_encoding cho {v['check']} chưa có phép kiểm", False)


def _check_wrong_pin(c, n, v, p, data) -> None:
    c.true(f"{n} pin_used là 6 chữ số khác PIN", v["pin_used"] != p.v["pin"] and len(v["pin_used"]) == 6
           and v["pin_used"].isdigit())
    k = argon2id(v["pin_used"], p.salt, SPEC_ARGON2)
    key = hkdf(k, b"handlive/v1/pair-auth", 32, p.salt)
    c.eq(f"{n} k_pin_used, mac_key", (v["k_pin_used"], v["mac_key"]), (k.hex(), key.hex()))
    c.eq(f"{n} mac = HMAC(K_pa của PIN sai, T_offer)", hmac256(key, p.t_offer), b64u_decode(data["mac"]))
    reply = read_message(c, f"{n} client_reply", v["client_reply_envelope"], v["client_reply_plaintext"], "error")
    c.eq(f"{n} client trả PIN_INVALID còn 2 lần", (reply["code"], reply["attempts_left"]), ("PIN_INVALID", 2))


def check(c, doc, pairings: dict) -> None:
    reasons, kinds = set(), set()
    for v in doc["invalid_vectors"]:
        n = f"pair-handshake/{v['name']}"
        p = pairings[v["vector"]]
        data = None
        if v["message"] is not None:
            data = read_message(c, n, v["envelope"], v["plaintext"], v["message"])
        c.eq(f"{n} thất bại đúng ở phép kiểm", _failure(p, v, data), v["check"])
        c.eq(f"{n} checked_by", v["checked_by"], CHECKED_BY[v["message"]])
        c.eq(f"{n} expected_error", v["expected_error"], _expected_error(p, v))
        _check_reason(c, n, v, p, data)
        reasons.add(v["reason"])
        kinds.add(v["message"] or v["check"])
    c.eq("pair-handshake: đủ loại vector âm", reasons, REQUIRED_REASONS)
    c.eq("pair-handshake: vector âm cho mọi thông điệp", kinds, {"hello", "offer", "confirm", "done", "k_pin", "pr"})
    c.eq("pair-handshake: tên vector âm duy nhất", len({v["name"] for v in doc["invalid_vectors"]}),
         len(doc["invalid_vectors"]))
