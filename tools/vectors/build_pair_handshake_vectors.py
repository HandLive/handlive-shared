"""Dựng pair-handshake.json: toàn bộ bắt tay PAIR-01 (QR và PIN) và mã an toàn PAIR-02 trường 10.

Khóa lấy lại của pair-prk.json (ik_sig = RFC 8032 §7.1 TEST 1–3, ik_dh = Alice/Bob của RFC 7748 §6.1): vector QR
dùng đúng cặp 1 / cặp 2 kể cả pairing_secret và pair_id, nên PRK trùng pair-prk.json; vector PIN dùng khóa của cặp 1
với pair_id mới và K_pin thay cho pairing_secret. Vector âm do build_pair_handshake_negative_vectors.py dựng.
"""
import unicodedata

import pair_handshake_messages as M
import pairing_discovery_derivations as P
import rfc_source_values as R
from build_pair_handshake_negative_vectors import negatives
from handlive_protocol_derivations import (b64u, compact_json, device_id_from_pub, ed25519_pub, ed25519_sign, hkdf,
                                           pair_salt_input, test_bytes, x25519_dh, x25519_pub)

H = bytes.fromhex
SPEC = "docs/detailed-design/02-pairing.md"
COMMON = "docs/detailed-design/00-common-specs.md"
PRK_INFO = "handlive/v1/pair"
CASES = [
    {"name": "QR cặp 1", "mode": "qr", "keys_from": "cặp 1", "pair_id": None, "created_at": 1727150003210,
     "client": ("MacBook của Lan", "macos", "Mac15,3"), "android": ("Pixel của Lan", "Pixel 8", "15"), "rv": False,
     "pin": None},
    # Tên client có "&" (phải mã hóa %26 trong QR); tên điện thoại ở dạng Unicode NFD (không được chuẩn hóa).
    {"name": "QR cặp 2", "mode": "qr", "keys_from": "cặp 2", "pair_id": None, "created_at": 1727152003210,
     "client": ("iPhone của Minh & Hà", "ios", "iPhone16,1"),
     "android": (unicodedata.normalize("NFD", "Galaxy của Hà"), "SM-S921B", "14"), "rv": True, "pin": None},
    # PIN có số 0 đầu: K_pin băm đúng 6 ký tự chữ số, không đổi sang số nguyên.
    {"name": "PIN cặp 3", "mode": "pin", "keys_from": "cặp 1", "pair_id": "7c6b5a49-3827-4165-9f4e-3d2c1b0a9f8e",
     "created_at": 1727153003210, "client": ("MacBook của Lan", "macos", "Mac15,3"),
     "android": ("Pixel của Lan", "Pixel 8", "15"), "rv": False, "pin": "042917"},
]


def _seed_for(pub_hex: str) -> bytes:
    return H(next(seed for _, seed, pub in R.ED25519_8032 if pub == pub_hex))


def _state(case: dict, pv: dict) -> dict:
    """Mọi giá trị thô của một lần ghép nối, dùng chung cho vector dương và vector âm."""
    name = case["name"]
    s = {"name": name, "mode": case["mode"], "pair_id": case["pair_id"] or pv["pair_id"],
         "created_at": case["created_at"], "keys_from": case["keys_from"]}
    s["c_name"], s["c_platform"], s["c_model"] = case["client"]
    s["a_name"], s["a_model"], s["a_os"] = case["android"]
    s["c_seed"], s["a_seed"] = _seed_for(pv["client_ik_sig_pub"]), _seed_for(pv["android_ik_sig_pub"])
    s["c_pub"], s["a_pub"] = ed25519_pub(s["c_seed"]), ed25519_pub(s["a_seed"])
    s["c_id"], s["a_id"] = device_id_from_pub(s["c_pub"]), device_id_from_pub(s["a_pub"])
    assert (s["c_id"], s["a_id"]) == (pv["client_device_id"], pv["android_device_id"])
    s["c_dh"], s["a_dh"] = H(pv["client_ik_dh_priv"]), H(pv["android_ik_dh_priv"])
    s["c_dh_pub"], s["a_dh_pub"] = x25519_pub(s["c_dh"]), x25519_pub(s["a_dh"])
    s["nonce_c"], s["nonce_s"] = test_bytes(f"{name} nonce_c", 32), test_bytes(f"{name} nonce_s", 32)
    s["tls"] = test_bytes(f"{name} tls_sha256", 32)
    s["pin"], s["rv"], s["uri"], s["k_pin"], s["pairing_secret"] = case["pin"], None, None, None, None
    if case["mode"] == "qr":
        s["pairing_secret"] = s["secret"] = H(pv["pairing_secret"])
        s["rv"] = test_bytes(f"{name} rv", 16) if case["rv"] else None
        s["uri"] = P.qr_uri(s["c_dh_pub"], s["secret"], s["c_name"], s["rv"])
        assert len(s["uri"]) <= 300, "API 1 quy tắc 1: URI ≤ 300 ký tự"
    else:
        s["k_pin"] = s["secret"] = P.pin_key(case["pin"], s["nonce_c"], s["nonce_s"])
    s["k_pa"] = P.pair_auth_key(s["secret"], s["nonce_c"], s["nonce_s"])
    s["client_party"] = {"device_id": s["c_id"], "nonce": s["nonce_c"], "ik_sig_pub": s["c_pub"],
                         "ik_dh_pub": s["c_dh_pub"], "name": s["c_name"]}
    s["server_party"] = {"device_id": s["a_id"], "nonce": s["nonce_s"], "ik_sig_pub": s["a_pub"],
                         "ik_dh_pub": s["a_dh_pub"], "name": s["a_name"]}
    s["t_offer_parts"] = P.offer_parts(s["client_party"], s["server_party"], s["tls"])
    s["t_offer"] = P.joined(s["t_offer_parts"])
    s["offer_mac"] = P.hmac_sha256(s["k_pa"], s["t_offer"])
    s["attestation_parts"] = P.attestation_parts(s["pair_id"], s["a_id"], s["c_id"], s["a_pub"], s["c_pub"],
                                                 s["created_at"])
    s["attestation"] = P.joined(s["attestation_parts"])
    s["sig_c"], s["sig_s"] = ed25519_sign(s["c_seed"], s["attestation"]), ed25519_sign(s["a_seed"], s["attestation"])
    s["confirm_parts"] = P.confirm_parts(s["t_offer"], s["pair_id"], s["created_at"], s["sig_c"])
    s["confirm_mac"] = P.hmac_sha256(s["k_pa"], P.joined(s["confirm_parts"]))
    s["done_parts"] = P.done_parts(s["pair_id"], s["sig_s"])
    s["done_mac"] = P.hmac_sha256(s["k_pa"], P.joined(s["done_parts"]))
    s["dh"] = x25519_dh(s["c_dh"], s["a_dh_pub"])
    assert s["dh"] == x25519_dh(s["a_dh"], s["c_dh_pub"])
    s["prk_salt_input"] = pair_salt_input(s["c_id"], s["a_id"])
    s["prk_salt"] = P.sha256(s["prk_salt_input"])
    s["prk"] = hkdf(s["dh"] + s["secret"], PRK_INFO.encode(), 32, s["prk_salt"])
    if case["mode"] == "qr":
        assert s["prk"].hex() == pv["prk"], f"{name}: PRK phải trùng pair-prk.json"
    s["prk_check_c_input"] = P.prk_check_input("client", s["pair_id"])
    s["prk_check_s_input"] = P.prk_check_input("server", s["pair_id"])
    s["prk_check_c"] = P.hmac_sha256(s["prk"], s["prk_check_c_input"])
    s["prk_check_s"] = P.hmac_sha256(s["prk"], s["prk_check_s_input"])
    return s


def _vector(s: dict) -> dict:
    qr = s["mode"] == "qr"
    msgs = {}
    for op in ("hello", "offer", "confirm", "done"):
        msgs[f"{op}_plaintext"], msgs[f"{op}_envelope"] = M.message(s, op)
    pairs_request = compact_json({"pair_id": s["pair_id"], "device_a": s["a_id"], "device_b": s["c_id"],
                                  "created_at": s["created_at"], "attestation": b64u(s["attestation"]),
                                  "sig_a": b64u(s["sig_s"]), "sig_b": b64u(s["sig_c"])})
    return {
        "name": s["name"], "mode": s["mode"], "pair_id": s["pair_id"], "keys_from": f"pair-prk.json/{s['keys_from']}",
        "client_ik_sig_seed": s["c_seed"].hex(), "client_ik_sig_pub": s["c_pub"].hex(), "client_device_id": s["c_id"],
        "client_ik_dh_priv": s["c_dh"].hex(), "client_ik_dh_pub": s["c_dh_pub"].hex(), "client_name": s["c_name"],
        "client_platform": s["c_platform"], "client_model": s["c_model"],
        "android_ik_sig_seed": s["a_seed"].hex(), "android_ik_sig_pub": s["a_pub"].hex(),
        "android_device_id": s["a_id"], "android_ik_dh_priv": s["a_dh"].hex(), "android_ik_dh_pub": s["a_dh_pub"].hex(),
        "android_name": s["a_name"], "android_model": s["a_model"], "android_os_version": s["a_os"],
        "tls_sha256": s["tls"].hex(),
        "qr_uri": s["uri"], "qr_pk": b64u(s["c_dh_pub"]) if qr else None,
        "qr_ps": b64u(s["pairing_secret"]) if qr else None, "qr_rv": s["rv"].hex() if s["rv"] is not None else None,
        "pr": P.pairing_request_hint(s["c_dh_pub"]) if qr else None,
        "pairing_secret": s["pairing_secret"].hex() if qr else None,
        "pin": s["pin"], "argon2": None if qr else dict(P.PIN_ARGON2), "k_pin": None if qr else s["k_pin"].hex(),
        "nonce_c": s["nonce_c"].hex(), "nonce_s": s["nonce_s"].hex(), "secret": s["secret"].hex(),
        "k_pa_salt": (s["nonce_c"] + s["nonce_s"]).hex(), "k_pa_info": P.PAIR_AUTH_INFO, "k_pa": s["k_pa"].hex(),
        "t_offer_parts": P.parts_json(s["t_offer_parts"]), "t_offer": s["t_offer"].hex(),
        "offer_mac": s["offer_mac"].hex(), "created_at": s["created_at"],
        "attestation_parts": P.parts_json(s["attestation_parts"]), "attestation": s["attestation"].hex(),
        "sig_c": s["sig_c"].hex(), "sig_s": s["sig_s"].hex(), "security_code": P.security_code(s["attestation"]),
        "confirm_mac_input_parts": P.parts_json(s["confirm_parts"]),
        "confirm_mac_input": P.joined(s["confirm_parts"]).hex(), "confirm_mac": s["confirm_mac"].hex(),
        "done_mac_input_parts": P.parts_json(s["done_parts"]), "done_mac_input": P.joined(s["done_parts"]).hex(),
        "done_mac": s["done_mac"].hex(),
        "dh_shared": s["dh"].hex(), "prk_ikm": (s["dh"] + s["secret"]).hex(),
        "prk_salt_input": s["prk_salt_input"].hex(), "prk_salt": s["prk_salt"].hex(), "prk_info": PRK_INFO,
        "prk": s["prk"].hex(),
        "prk_check_c_input": s["prk_check_c_input"].hex(), "prk_check_c": s["prk_check_c"].hex(),
        "prk_check_s_input": s["prk_check_s_input"].hex(), "prk_check_s": s["prk_check_s"].hex(),
        **msgs, "pairs_request": pairs_request,
    }


DESCRIPTION = (
    "Bắt tay ghép nối PAIR-01 (QR và PIN) trọn vẹn. Mọi chuỗi MAC/ký ghép BYTE thô, không JSON: uuid 16 byte, "
    "created_at int64 BE, sig 64 byte, str(x) = uint16 BE số byte ‖ UTF-8 (không chuẩn hóa Unicode). Nhãn ASCII không "
    "dấu cách: \"HL1|offer|\", \"HL1|confirm|\", \"HL1|done|\", \"HL1|prk-check-c|\", \"HL1|prk-check-s|\", "
    "\"HLPAIR1\". secret = pairing_secret (QR) hoặc K_pin = Argon2id v0x13(UTF-8 của 6 chữ số PIN, salt nonce_c ‖ "
    "nonce_s, t 3, m 65536 KiB, p 4, L 32) (PIN). K_pa = HKDF(secret, salt nonce_c ‖ nonce_s, info "
    "\"handlive/v1/pair-auth\", L 32). offer_mac = HMAC(K_pa, T_offer); confirm_mac = HMAC(K_pa, \"HL1|confirm|\" ‖ "
    "T_offer ‖ pair_id ‖ created_at ‖ sig_c); done_mac = HMAC(K_pa, \"HL1|done|\" ‖ pair_id ‖ sig_s). PRK = HKDF(X25519 "
    "‖ secret, salt SHA-256(device_id nhỏ ‖ lớn), info \"handlive/v1/pair\", L 32); prk_check_c/s = HMAC(PRK, nhãn ‖ "
    "pair_id). attestation = \"HLPAIR1\" ‖ pair_id ‖ device_id Android ‖ device_id client ‖ ik_sig_pub Android ‖ "
    "ik_sig_pub client ‖ created_at; sig_c/sig_s = Ed25519 của client/Android trên attestation; security_code = 8 hex "
    "thường đầu của SHA-256(attestation). pr = 8 hex thường đầu của SHA-256(32 byte của pk). Vector âm: phép kiểm "
    "`check` do `checked_by` chạy phải thất bại ĐÚNG ở chỗ đó, với mã lỗi `expected_error`; `reason` nói lỗi dựng "
    "vector là gì.")


def build(ctx: dict) -> dict:
    prk_vectors = {v["name"]: v for v in ctx["pairs"]}
    states = [_state(case, prk_vectors[case["keys_from"]]) for case in CASES]
    doc = {"description": DESCRIPTION,
           "source": f"{SPEC} PAIR-01 API 1–8, PAIR-02 trường 10; {COMMON} 0.4.1, 0.6.2; khóa của pair-prk.json",
           "vectors": [_vector(s) for s in states],
           "invalid_vectors": negatives({s["name"]: s for s in states})}
    return {"pair-handshake.json": doc}
