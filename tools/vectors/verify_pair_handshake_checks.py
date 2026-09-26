"""Kiểm vector dương của pair-handshake.json bằng thư viện độc lập với phía sinh (xem verify_pairing_common.py).

Mọi giá trị được tính lại từ khóa bí mật, PIN/pairing_secret và JSON của bốn thông điệp `pair`; khóa và PRK nối chuỗi
với pair-prk.json và device-id.json. Vector âm: verify_pair_handshake_negative_checks.py.
"""
import json
import struct
from urllib.parse import parse_qs, urlsplit

from nacl.signing import SigningKey

import verify_pair_handshake_negative_checks as negative
from verify_common import H, b64u, b64u_decode, ed25519_pub, hkdf, hmac256, sha256, uuid16, x25519_base
from verify_pairing_common import (FIELDS, SPEC_ARGON2, Pairing, argon2id, confirm_input, done_input, read_message,
                                   str_field)
from verify_session_checks import device_id
from verify_signature_checks import verifies


def _parts(c, where: str, parts: list[dict], whole: str, expected: list[tuple[str, bytes]]) -> None:
    c.eq(f"{where} parts ghép lại = toàn chuỗi", "".join(p["hex"] for p in parts), whole)
    c.eq(f"{where} parts", [(p["field"], p["hex"]) for p in parts], [(f, b.hex()) for f, b in expected])


def _check_keys(c, n: str, v: dict, p: Pairing, all_docs: dict) -> None:
    pair_prk = {f"pair-prk.json/{x['name']}": x for x in all_docs["pair-prk.json"]["vectors"]}
    ids = {(x["ik_sig_seed"], x["ik_sig_pub"], x["device_id"]) for x in all_docs["device-id.json"]["vectors"]}
    pv = pair_prk[v["keys_from"]]
    for side in ("client", "android"):
        seed, pub = H(v[f"{side}_ik_sig_seed"]), H(v[f"{side}_ik_sig_pub"])
        c.eq(f"{n} {side} ik_sig_pub từ seed", ed25519_pub(seed), pub)
        c.eq(f"{n} {side} device_id", device_id(pub), v[f"{side}_device_id"])
        c.true(f"{n} {side} khóa có trong device-id.json", (v[f"{side}_ik_sig_seed"], v[f"{side}_ik_sig_pub"],
                                                           v[f"{side}_device_id"]) in ids)
        c.eq(f"{n} {side} ik_dh_pub từ khóa riêng", x25519_base(H(v[f"{side}_ik_dh_priv"])).hex(), v[f"{side}_ik_dh_pub"])
        for key in ("ik_sig_pub", "device_id", "ik_dh_priv", "ik_dh_pub"):
            c.eq(f"{n} {side} {key} = {v['keys_from']}", v[f"{side}_{key}"], pv[f"{side}_{key}"])
    if p.qr:
        c.eq(f"{n} QR: pair_id, pairing_secret, prk = {v['keys_from']}", (v["pair_id"], v["pairing_secret"], v["prk"]),
             (pv["pair_id"], pv["pairing_secret"], pv["prk"]))


def _check_messages(c, n: str, v: dict, p: Pairing) -> None:
    for op in ("hello", "offer", "confirm", "done"):
        read_message(c, f"{n} {op}", v[f"{op}_envelope"], v[f"{op}_plaintext"], op)
    h, o = p.hello, p.offer
    c.eq(f"{n} hello", (h["mode"], h["device_id"], b64u_decode(h["nonce"]).hex(), h["name"], h["platform"], h["model"],
                        b64u_decode(h["ik_sig_pub"]).hex(), b64u_decode(h["ik_dh_pub"]).hex()),
         (v["mode"], v["client_device_id"], v["nonce_c"], v["client_name"], v["client_platform"], v["client_model"],
          v["client_ik_sig_pub"], v["client_ik_dh_pub"]))
    c.eq(f"{n} offer", (o["device_id"], b64u_decode(o["nonce"]).hex(), o["name"], o["model"], o["os_version"],
                        b64u_decode(o["ik_sig_pub"]).hex(), b64u_decode(o["ik_dh_pub"]).hex(),
                        b64u_decode(o["tls_sha256"]).hex(), b64u_decode(o["mac"]).hex()),
         (v["android_device_id"], v["nonce_s"], v["android_name"], v["android_model"], v["android_os_version"],
          v["android_ik_sig_pub"], v["android_ik_dh_pub"], v["tls_sha256"], v["offer_mac"]))
    c.eq(f"{n} confirm", (p.pair_id, p.created_at, b64u_decode(p.confirm["sig"]).hex(),
                          b64u_decode(p.confirm["prk_check"]).hex(), b64u_decode(p.confirm["mac"]).hex()),
         (v["pair_id"], v["created_at"], v["sig_c"], v["prk_check_c"], v["confirm_mac"]))
    c.eq(f"{n} done", (b64u_decode(p.done["sig"]).hex(), b64u_decode(p.done["prk_check"]).hex(),
                       b64u_decode(p.done["mac"]).hex()), (v["sig_s"], v["prk_check_s"], v["done_mac"]))
    c.true(f"{n} tên ≤ 64 ký tự", len(h["name"]) <= 64 and len(o["name"]) <= 64)
    c.true(f"{n} hello/offer/confirm/done đều qua phép kiểm của bên nhận",
           (p.hello_failure(h), p.offer_failure(o), p.confirm_failure(p.confirm), p.done_failure(p.done))
           == (None, None, None, None))
    b = uuid16(p.pair_id)
    c.true(f"{n} pair_id là UUIDv4", b[6] >> 4 == 4 and b[8] >> 6 == 2)


def _check_secret(c, n: str, v: dict, p: Pairing) -> None:
    if p.qr:
        u = urlsplit(v["qr_uri"])
        q = parse_qs(u.query, keep_blank_values=True, strict_parsing=True)
        c.eq(f"{n} QR scheme/host", (u.scheme, u.netloc, u.path), ("handlive", "pair", ""))
        c.true(f"{n} QR ≤ 300 ký tự, mỗi tham số một lần", len(v["qr_uri"]) <= 300 and all(len(x) == 1 for x in q.values()))
        c.eq(f"{n} QR v/pk/ps/d", (q["v"][0], b64u_decode(q["pk"][0]).hex(), b64u_decode(q["ps"][0]).hex(), q["d"][0]),
             ("1", v["client_ik_dh_pub"], v["pairing_secret"], v["client_name"]))
        c.eq(f"{n} QR rv", b64u_decode(q["rv"][0]).hex() if "rv" in q else None, v["qr_rv"])
        c.eq(f"{n} qr_pk/qr_ps", (v["qr_pk"], v["qr_ps"]), (q["pk"][0], q["ps"][0]))
        c.eq(f"{n} pr = 8 hex thường đầu của SHA-256(pk 32 byte)", v["pr"], sha256(p.pk)[:4].hex())
        c.eq(f"{n} secret = pairing_secret", v["secret"], v["pairing_secret"])
        c.eq(f"{n} không có trường PIN", (v["pin"], v["argon2"], v["k_pin"]), (None, None, None))
    else:
        c.true(f"{n} PIN là 6 chữ số", len(v["pin"]) == 6 and v["pin"].isascii() and v["pin"].isdigit())
        c.eq(f"{n} tham số Argon2id = 0.6.2", v["argon2"], SPEC_ARGON2)
        c.eq(f"{n} k_pin (argon2-cffi)", argon2id(v["pin"], p.salt, SPEC_ARGON2).hex(), v["k_pin"])
        c.eq(f"{n} secret = k_pin", v["secret"], v["k_pin"])
        c.eq(f"{n} không có trường QR", (v["qr_uri"], v["qr_pk"], v["qr_ps"], v["qr_rv"], v["pr"], v["pairing_secret"]),
             (None,) * 6)
    c.eq(f"{n} k_pa", (v["k_pa_salt"], v["k_pa_info"], v["k_pa"]),
         (p.salt.hex(), "handlive/v1/pair-auth", hkdf(p.secret, b"handlive/v1/pair-auth", 32, p.salt).hex()))


def _check_derivations(c, n: str, v: dict, p: Pairing) -> None:
    _parts(c, f"{n} t_offer", v["t_offer_parts"], v["t_offer"], p.t_offer_parts)
    c.eq(f"{n} t_offer", p.t_offer.hex(), v["t_offer"])
    c.eq(f"{n} offer_mac", hmac256(p.k_pa, p.t_offer).hex(), v["offer_mac"])
    att_parts = [("label", b"HLPAIR1"), ("pair_id", uuid16(p.pair_id)), ("device_id_android", uuid16(p.android_id)),
                 ("device_id_client", uuid16(p.client_id)), ("ik_sig_pub_android", p.android_pub),
                 ("ik_sig_pub_client", p.client_pub), ("created_at", struct.pack(">q", p.created_at))]
    _parts(c, f"{n} attestation", v["attestation_parts"], v["attestation"], att_parts)
    c.eq(f"{n} attestation 127 byte", (p.attestation.hex(), len(p.attestation)), (v["attestation"], 127))
    for side, key in (("c", "client"), ("s", "android")):
        sig = SigningKey(H(v[f"{key}_ik_sig_seed"])).sign(p.attestation).signature
        c.eq(f"{n} sig_{side} tất định (libsodium)", sig.hex(), v[f"sig_{side}"])
        c.true(f"{n} sig_{side} hợp lệ", verifies(H(v[f"{key}_ik_sig_pub"]), p.attestation, sig))
    c.eq(f"{n} security_code", v["security_code"], sha256(p.attestation)[:4].hex())
    sig_c, sig_s = H(v["sig_c"]), H(v["sig_s"])
    cm = confirm_input(p.t_offer, p.pair_id, p.created_at, sig_c)
    _parts(c, f"{n} confirm_mac_input", v["confirm_mac_input_parts"], v["confirm_mac_input"],
           [("label", b"HL1|confirm|"), ("t_offer", p.t_offer), ("pair_id", uuid16(p.pair_id)),
            ("created_at", struct.pack(">q", p.created_at)), ("sig", sig_c)])
    c.eq(f"{n} confirm_mac", (cm.hex(), hmac256(p.k_pa, cm).hex()), (v["confirm_mac_input"], v["confirm_mac"]))
    dm = done_input(p.pair_id, sig_s)
    _parts(c, f"{n} done_mac_input", v["done_mac_input_parts"], v["done_mac_input"],
           [("label", b"HL1|done|"), ("pair_id", uuid16(p.pair_id)), ("sig", sig_s)])
    c.eq(f"{n} done_mac", (dm.hex(), hmac256(p.k_pa, dm).hex()), (v["done_mac_input"], v["done_mac"]))
    c.eq(f"{n} dh hai phía", (p.dh.hex(), p.dh_android.hex()), (v["dh_shared"], v["dh_shared"]))
    c.eq(f"{n} PRK", (v["prk_ikm"], v["prk_salt_input"], v["prk_salt"], v["prk_info"], v["prk"]),
         ((p.dh + p.secret).hex(), p.prk_salt_input.hex(), sha256(p.prk_salt_input).hex(), "handlive/v1/pair",
          p.prk.hex()))
    for role, key in (("c", "prk_check_c"), ("s", "prk_check_s")):
        c.eq(f"{n} {key}", (v[f"{key}_input"], v[key]),
             ((f"HL1|prk-check-{role}|".encode() + uuid16(p.pair_id)).hex(), p.prk_check(role).hex()))
    req = json.loads(v["pairs_request"])
    c.eq(f"{n} pairs_request (API 8)", (list(req), req["pair_id"], req["device_a"], req["device_b"], req["created_at"],
                                        b64u_decode(req["attestation"]), req["sig_a"], req["sig_b"]),
         (["pair_id", "device_a", "device_b", "created_at", "attestation", "sig_a", "sig_b"], p.pair_id, p.android_id,
          p.client_id, p.created_at, p.attestation, b64u(sig_s), b64u(sig_c)))


def check_pair_handshake(c, doc, all_docs):
    pairings = {}
    for v in doc["vectors"]:
        n = f"pair-handshake/{v['name']}"
        p = pairings[v["name"]] = Pairing(v)
        c.eq(f"{n} str() đếm byte UTF-8", str_field(v["client_name"])[:2], struct.pack(">H", len(v["client_name"].encode())))
        _check_keys(c, n, v, p, all_docs)
        _check_secret(c, n, v, p)
        _check_messages(c, n, v, p)
        _check_derivations(c, n, v, p)
    vs = doc["vectors"]
    c.eq("pair-handshake có cả QR và PIN", {v["mode"] for v in vs}, {"qr", "pin"})
    c.eq("pair-handshake có QR có và không có rv", {v["qr_rv"] is None for v in vs if v["mode"] == "qr"}, {True, False})
    c.eq("pair-handshake có cả hai thứ tự device_id",
         {uuid16(v["client_device_id"]) < uuid16(v["android_device_id"]) for v in vs}, {True, False})
    c.eq("pair-handshake: FIELDS có đủ op", sorted(FIELDS), ["confirm", "done", "error", "hello", "offer"])
    negative.check(c, doc, pairings)


CHECKS = {"pair-handshake.json": check_pair_handshake}
