"""Vector âm của pair-handshake.json.

Mỗi mục là một thông điệp `pair` (hoặc một giá trị dẫn xuất) SAI vì đúng một lỗi cài đặt có thể gặp: nhãn có dấu cách
(ký tự `\\|` của bảng Markdown), sai thứ tự byte, sai mã hóa (chuỗi thay cho byte thô), MAC hay chữ ký bị sửa, sai PIN,
sai tham số Argon2id. Mục ghi phép kiểm phải thất bại (`check`), bên chạy phép kiểm (`checked_by`), mã lỗi mong đợi
(`expected_error`) và bằng chứng của lỗi (`mac_input`, `mac_key`, `signed_message`, `prk_used`, `pin_used`,
`k_pin_used`…) để bên kiểm xác nhận nó thất bại đúng vì lý do đã ghi, không vì một lỗi khác.
"""
import pair_handshake_messages as M
import pairing_discovery_derivations as P
import rfc_source_values as R
from handlive_protocol_derivations import b64u, device_id_from_pub, ed25519_sign, hkdf, test_bytes, uuid_bytes, x25519_pub

WRONG_PIN = "042971"
# Nhãn chép nhầm từ bảng Markdown của spec, nơi `|` được viết `\|` và hiện ra có dấu cách hai bên.
SPACED_LABEL = {"offer": b"HL1 | offer | ", "confirm": b"HL1 | confirm | ", "done": b"HL1 | done | "}


def _flip(data: bytes, index: int = 0, mask: int = 0x80) -> bytes:
    out = bytearray(data)
    out[index] ^= mask
    return bytes(out)


def _s_plus_l(sig: bytes) -> bytes:
    """Cùng chữ ký nhưng S thay bằng S + L (vẫn vừa 32 byte little endian): bên kiểm lỏng chấp nhận, bên kiểm chặt
    (RFC 8032 §5.1.7, 00-common-specs 0.6.5) phải từ chối."""
    s = int.from_bytes(sig[32:], "little") + R.ED25519_L
    assert s < 2**256
    return sig[:32] + s.to_bytes(32, "little")


def _entry(s: dict, message: str | None, check: str, checked_by: str, reason: str, expected_error: str | None,
           what: str, over: dict | None = None, **proof) -> dict:
    v = {"name": f"{s['name']} / {message or check}: {what}", "vector": s["name"], "message": message, "check": check,
         "checked_by": checked_by, "reason": reason, "expected_error": expected_error}
    if over is not None:
        v["plaintext"], v["envelope"] = M.message(s, message, **over)
    v.update({k: x.hex() if isinstance(x, bytes) else x for k, x in proof.items()})
    return v


def _hello(s: dict) -> list[dict]:
    stranger = x25519_pub(test_bytes("khóa DH lạ", 32))
    other_id = device_id_from_pub(bytes.fromhex(R.ED25519_8032[2][2]))
    assert other_id != s["c_id"]
    return [
        _entry(s, "hello", "hello_key", "android", "key_mismatch", "AUTH_FAILED", "ik_dh_pub khác pk đã quét trong QR",
               {"ik_dh_pub": b64u(stranger)}),
        _entry(s, "hello", "hello_device_id", "android", "device_id_mismatch", "AUTH_FAILED",
               "device_id không dẫn xuất từ ik_sig_pub", {"device_id": other_id}),
    ]


def _offer(q1: dict, q2: dict) -> list[dict]:
    spaced = P.joined(P.offer_parts(q1["client_party"], q1["server_party"], q1["tls"], label=SPACED_LABEL["offer"]))
    little = P.joined(P.offer_parts(q1["client_party"], q1["server_party"], q1["tls"], str_order="<"))
    swapped_key = hkdf(q2["secret"], P.PAIR_AUTH_INFO.encode(), 32, q2["nonce_s"] + q2["nonce_c"])
    attacker_tls = test_bytes("tls_sha256 kẻ tấn công", 32)
    return [
        _entry(q1, "offer", "offer_mac", "client", "mac_mismatch", "AUTH_FAILED", "mac sửa 1 bit",
               {"mac": b64u(_flip(q1["offer_mac"]))}),
        _entry(q1, "offer", "offer_mac", "client", "wrong_label", "AUTH_FAILED", "nhãn \"HL1 | offer | \" có dấu cách",
               {"mac": b64u(P.hmac_sha256(q1["k_pa"], spaced))}, mac_input=spaced),
        _entry(q1, "offer", "offer_mac", "client", "wrong_byte_order", "AUTH_FAILED",
               "độ dài của str(name) viết little-endian", {"mac": b64u(P.hmac_sha256(q1["k_pa"], little))},
               mac_input=little),
        _entry(q2, "offer", "offer_mac", "client", "wrong_byte_order", "AUTH_FAILED",
               "salt của K_pa đảo thành nonce_s ‖ nonce_c", {"mac": b64u(P.hmac_sha256(swapped_key, q2["t_offer"]))},
               mac_key=swapped_key),
        _entry(q2, "offer", "offer_mac", "client", "message_tampered", "AUTH_FAILED",
               "tls_sha256 bị thay trên đường (MITM), mac giữ nguyên", {"tls_sha256": b64u(attacker_tls)},
               mac_input=q2["t_offer"]),
    ]


def _pin(s: dict) -> list[dict]:
    wrong_key = P.pin_key(WRONG_PIN, s["nonce_c"], s["nonce_s"])
    wrong_auth = P.pair_auth_key(wrong_key, s["nonce_c"], s["nonce_s"])
    reply = M.plaintext("error", {"code": "PIN_INVALID", "message": "PIN does not match", "attempts_left": 2})
    one_lane = {**P.PIN_ARGON2, "p": 1}
    unpadded = str(int(s["pin"]))
    return [
        _entry(s, "offer", "offer_mac", "client", "wrong_pin", "PIN_INVALID",
               f"người dùng nhập sai PIN trên điện thoại ({WRONG_PIN})",
               {"mac": b64u(P.hmac_sha256(wrong_auth, s["t_offer"]))}, pin_used=WRONG_PIN, k_pin_used=wrong_key,
               mac_key=wrong_auth, client_reply_plaintext=reply, client_reply_envelope=M.envelope(s, "error", reply)),
        _entry(s, None, "k_pin", "both", "wrong_parameters", "PIN_INVALID",
               "Argon2id với p = 1 (số lane cố định của libsodium)", pin_used=s["pin"], argon2_used=one_lane,
               k_pin_used=P.pin_key(s["pin"], s["nonce_c"], s["nonce_s"], one_lane)),
        _entry(s, None, "k_pin", "both", "wrong_encoding", "PIN_INVALID",
               f"PIN đổi sang số nguyên nên mất số 0 đầu (\"{unpadded}\")", pin_used=unpadded,
               k_pin_used=P.pin_key(unpadded, s["nonce_c"], s["nonce_s"])),
    ]


def _confirm_mac(s: dict, parts: list) -> bytes:
    return P.hmac_sha256(s["k_pa"], P.joined(parts))


def _confirm_with_sig(s: dict, sig: bytes) -> dict:
    """sig khác nhưng mac tính lại trên chính sig đó: phép kiểm mac và prk_check qua, chỉ chữ ký hỏng."""
    return {"sig": b64u(sig), "mac": b64u(_confirm_mac(s, P.confirm_parts(s["t_offer"], s["pair_id"],
                                                                          s["created_at"], sig)))}


def _confirm(q1: dict, q2: dict) -> list[dict]:
    spaced = P.confirm_parts(q1["t_offer"], q1["pair_id"], q1["created_at"], q1["sig_c"], label=SPACED_LABEL["confirm"])
    little = P.confirm_parts(q1["t_offer"], q1["pair_id"], q1["created_at"], q1["sig_c"], int_order="<")
    sig_text = P.confirm_parts(q1["t_offer"], q1["pair_id"], q1["created_at"], b64u(q1["sig_c"]).encode())
    id_text = [(f, q2["pair_id"].encode() if f == "pair_id" else b) for f, b in q2["confirm_parts"]]
    server_label = P.prk_check_input("server", q2["pair_id"])
    smaller, larger = sorted([uuid_bytes(q2["c_id"]), uuid_bytes(q2["a_id"])])
    reversed_salt = larger + smaller
    reversed_prk = hkdf(q2["dh"] + q2["secret"], b"handlive/v1/pair", 32, P.sha256(reversed_salt))
    att_little = P.joined(P.attestation_parts(q1["pair_id"], q1["a_id"], q1["c_id"], q1["a_pub"], q1["c_pub"],
                                              q1["created_at"], int_order="<"))
    att_client_first = P.joined(P.attestation_parts(q2["pair_id"], q2["c_id"], q2["a_id"], q2["c_pub"], q2["a_pub"],
                                                    q2["created_at"]))
    sig_little, sig_client_first = ed25519_sign(q1["c_seed"], att_little), ed25519_sign(q2["c_seed"], att_client_first)
    return [
        _entry(q1, "confirm", "confirm_mac", "android", "mac_mismatch", "AUTH_FAILED", "mac sửa 1 bit",
               {"mac": b64u(_flip(q1["confirm_mac"]))}),
        _entry(q1, "confirm", "confirm_mac", "android", "wrong_label", "AUTH_FAILED",
               "nhãn \"HL1 | confirm | \" có dấu cách", {"mac": b64u(_confirm_mac(q1, spaced))},
               mac_input=P.joined(spaced)),
        _entry(q1, "confirm", "confirm_mac", "android", "wrong_byte_order", "AUTH_FAILED",
               "created_at viết int64 little-endian trong chuỗi MAC", {"mac": b64u(_confirm_mac(q1, little))},
               mac_input=P.joined(little)),
        _entry(q1, "confirm", "confirm_mac", "android", "wrong_encoding", "AUTH_FAILED",
               "sig ghép ở dạng chuỗi b64u thay vì 64 byte thô", {"mac": b64u(_confirm_mac(q1, sig_text))},
               mac_input=P.joined(sig_text)),
        _entry(q2, "confirm", "confirm_mac", "android", "wrong_encoding", "AUTH_FAILED",
               "pair_id ghép ở dạng chuỗi 36 ký tự thay vì 16 byte", {"mac": b64u(_confirm_mac(q2, id_text))},
               mac_input=P.joined(id_text)),
        _entry(q1, "confirm", "prk_check_c", "android", "mac_mismatch", "AUTH_FAILED", "prk_check sửa 1 bit",
               {"prk_check": b64u(_flip(q1["prk_check_c"]))}),
        _entry(q2, "confirm", "prk_check_c", "android", "wrong_label", "AUTH_FAILED",
               "prk_check dùng nhãn của Android \"HL1|prk-check-s|\"",
               {"prk_check": b64u(P.hmac_sha256(q2["prk"], server_label))}, prk_check_input=server_label),
        _entry(q2, "confirm", "prk_check_c", "android", "wrong_byte_order", "AUTH_FAILED",
               "PRK tính với salt = SHA-256(device_id lớn ‖ nhỏ)",
               {"prk_check": b64u(P.hmac_sha256(reversed_prk, q2["prk_check_c_input"]))},
               prk_salt_input_used=reversed_salt, prk_used=reversed_prk),
        _entry(q1, "confirm", "sig_c", "android", "signature_mismatch", "AUTH_FAILED",
               "sig sửa 1 bit (mac tính lại cho khớp)", _confirm_with_sig(q1, _flip(q1["sig_c"], 0, 0x01))),
        _entry(q1, "confirm", "sig_c", "android", "wrong_byte_order", "AUTH_FAILED",
               "sig ký attestation có created_at little-endian (mac tính lại cho khớp)",
               _confirm_with_sig(q1, sig_little), signed_message=att_little),
        _entry(q2, "confirm", "sig_c", "android", "wrong_field_order", "AUTH_FAILED",
               "sig ký attestation đặt device_id và khóa của client trước Android (mac tính lại cho khớp)",
               _confirm_with_sig(q2, sig_client_first), signed_message=att_client_first),
        _entry(q2, "confirm", "sig_c", "android", "signature_not_canonical", "AUTH_FAILED",
               "sig có S + L, không chính tắc (mac tính lại cho khớp)", _confirm_with_sig(q2, _s_plus_l(q2["sig_c"]))),
    ]


def _done(q1: dict, q2: dict) -> list[dict]:
    spaced = P.done_parts(q1["pair_id"], q1["sig_s"], label=SPACED_LABEL["done"])
    client_label = P.prk_check_input("client", q2["pair_id"])
    bad_sig = _flip(q2["sig_s"], 0, 0x01)
    return [
        _entry(q1, "done", "done_mac", "client", "mac_mismatch", "AUTH_FAILED", "mac sửa 1 bit",
               {"mac": b64u(_flip(q1["done_mac"]))}),
        _entry(q1, "done", "done_mac", "client", "wrong_label", "AUTH_FAILED", "nhãn \"HL1 | done | \" có dấu cách",
               {"mac": b64u(P.hmac_sha256(q1["k_pa"], P.joined(spaced)))}, mac_input=P.joined(spaced)),
        _entry(q2, "done", "prk_check_s", "client", "wrong_label", "AUTH_FAILED",
               "prk_check dùng nhãn của client \"HL1|prk-check-c|\"",
               {"prk_check": b64u(P.hmac_sha256(q2["prk"], client_label))}, prk_check_input=client_label),
        _entry(q2, "done", "sig_s", "client", "signature_mismatch", "AUTH_FAILED", "sig sửa 1 bit (mac tính lại cho khớp)",
               {"sig": b64u(bad_sig),
                "mac": b64u(P.hmac_sha256(q2["k_pa"], P.joined(P.done_parts(q2["pair_id"], bad_sig))))}),
    ]


def _pr(s: dict) -> list[dict]:
    text = b64u(s["c_dh_pub"]).encode()
    return [_entry(s, None, "pr", "both", "wrong_encoding", None,
                   "SHA-256 trên chuỗi b64u của pk thay vì 32 byte đã giải", pr=P.first_hex8(P.sha256(text)),
                   pr_input=text)]


def negatives(states: dict) -> list[dict]:
    q1, q2, pin = states["QR cặp 1"], states["QR cặp 2"], states["PIN cặp 3"]
    return _hello(q1) + _offer(q1, q2) + _pin(pin) + _confirm(q1, q2) + _done(q1, q2) + _pr(q1)
