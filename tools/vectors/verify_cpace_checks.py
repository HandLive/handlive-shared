"""Kiểm cpace.json bằng thư viện độc lập. `calculate_generator`/`generator_string` (Elligator2) dùng lại
`cpace_x25519_sha512.py` vì không có thư viện khác cho map_to_curve_elligator2 — giống cách `hchacha20_reference.py`
dùng chung cho HChaCha20 (verify_common.py); đã đối chiếu byte-exact với Appendix B.1.1 của draft trong
`build_cpace_vectors.py`. X25519/scalar_mult_vfy ở đây qua pynacl (phía sinh dùng `cryptography`); lv_cat,
transcript, ISK, HKDF cài lại bằng hashlib/hmac, độc lập với `cpace_x25519_sha512.py` và
`handlive_protocol_derivations.py`.
"""
import hashlib

from nacl.bindings import crypto_scalarmult
from nacl.exceptions import CryptoError

from cpace_x25519_sha512 import calculate_generator
from verify_common import H, hkdf

DSI_ISK = b"CPace255_ISK"
REASONS = {"low_order_ya", "low_order_yb", "sid_mismatch", "wrong_pin"}


def _prepend_len(data: bytes) -> bytes:
    length, out = len(data), bytearray()
    while True:
        out.append(length if length < 128 else (length & 0x7F) + 0x80)
        length >>= 7
        if length == 0:
            break
    return bytes(out) + data


def _lv_cat(*parts: bytes) -> bytes:
    return b"".join(_prepend_len(p) for p in parts)


def _transcript_ir(ya: bytes, ada: bytes, yb: bytes, adb: bytes) -> bytes:
    return _lv_cat(ya, ada) + _lv_cat(yb, adb)


def _isk(sid: bytes, k: bytes, ya: bytes, ada: bytes, yb: bytes, adb: bytes) -> bytes:
    return hashlib.sha512(_lv_cat(DSI_ISK, sid, k) + _transcript_ir(ya, ada, yb, adb)).digest()


def _scalar_mult_vfy(scalar: bytes, point: bytes) -> bytes | None:
    try:
        return crypto_scalarmult(scalar, point)
    except CryptoError:
        return None


def _check_official_generator(c, n: str, v: dict) -> None:
    g = calculate_generator(H(v["PRS"]), H(v["CI"]), H(v["sid"]))
    c.eq(f"{n} g (Elligator2)", v["g"], g.hex())


def _check_official_message(c, n: str, v: dict) -> None:
    g = calculate_generator(H(v["PRS"]), H(v["CI"]), H(v["sid"]))
    c.eq(f"{n} g", v["g"], g.hex())
    Ya = _scalar_mult_vfy(H(v["ya"]), g)
    Yb = _scalar_mult_vfy(H(v["yb"]), g)
    c.eq(f"{n} Ya = scalar_mult_vfy(ya, g)", v["Ya"], Ya.hex() if Ya else None)
    c.eq(f"{n} Yb = scalar_mult_vfy(yb, g)", v["Yb"], Yb.hex() if Yb else None)
    k_a = _scalar_mult_vfy(H(v["ya"]), Yb)
    k_b = _scalar_mult_vfy(H(v["yb"]), Ya)
    c.eq(f"{n} K khớp cả hai phía", (v["K"], v["K"]), (k_a.hex() if k_a else None, k_b.hex() if k_b else None))
    isk = _isk(H(v["sid"]), H(v["K"]), Ya, H(v["ADa"]), Yb, H(v["ADb"]))
    c.eq(f"{n} ISK (khởi tạo/trả lời)", v["ISK_initiator_responder"], isk.hex())


def _check_handlive_pin(c, n: str, v: dict) -> None:
    prs, ci, n_s = v["pin"].encode("utf-8"), v["ci"].encode("utf-8"), H(v["n_s"])
    c.eq(f"{n} ci = HLBTPIN1 (0.4.5 luồng C)", v["ci"], "HLBTPIN1")
    g = calculate_generator(prs, ci, n_s)
    c.eq(f"{n} g", v["g"], g.hex())
    Ya = _scalar_mult_vfy(H(v["ya"]), g)
    Yb = _scalar_mult_vfy(H(v["yb"]), g)
    c.eq(f"{n} Ya", v["Ya"], Ya.hex() if Ya else None)
    c.eq(f"{n} Yb", v["Yb"], Yb.hex() if Yb else None)
    k_a = _scalar_mult_vfy(H(v["ya"]), Yb)
    c.eq(f"{n} K", v["K"], k_a.hex() if k_a else None)
    isk = _isk(n_s, H(v["K"]), Ya, b"", Yb, b"")
    c.eq(f"{n} ISK", v["ISK"], isk.hex())
    c.eq(f"{n} K_bt_pinlink", v["k_bt_pinlink"], hkdf(isk, v["k_bt_pinlink_info"].encode(), 32, salt=n_s).hex())
    c.eq(f"{n} K_bt_pin", v["k_bt_pin"], hkdf(isk, v["k_bt_pin_info"].encode(), 32, salt=n_s).hex())


def _check_negative(c, n: str, v: dict) -> None:
    reason = v["reason"]
    c.true(f"{n} reason nằm trong tập đã định", reason in REASONS)
    if reason in ("low_order_ya", "low_order_yb"):
        g = calculate_generator(v["pin"].encode("utf-8"), b"HLBTPIN1", H(v["n_s"]))
        c.eq(f"{n} g", v["g"], g.hex())
        if reason == "low_order_ya":
            k_s = _scalar_mult_vfy(H(v["yb"]), H(v["Ya_attacker"]))
        else:
            k_s = _scalar_mult_vfy(H(v["ya"]), H(v["Yb_attacker"]))
        c.eq(f"{n} K phải là None (G.I, điểm bậc thấp)", k_s, None)
    elif reason == "sid_mismatch":
        g_c = calculate_generator(v["pin"].encode("utf-8"), b"HLBTPIN1", H(v["n_s_c"]))
        g_s = calculate_generator(v["pin"].encode("utf-8"), b"HLBTPIN1", H(v["n_s_s"]))
        Ya, Yb = _scalar_mult_vfy(H(v["ya"]), g_c), _scalar_mult_vfy(H(v["yb"]), g_s)
        c.eq(f"{n} Ya", v["Ya"], Ya.hex() if Ya else None)
        c.eq(f"{n} Yb", v["Yb"], Yb.hex() if Yb else None)
        k_c, k_s = _scalar_mult_vfy(H(v["ya"]), Yb), _scalar_mult_vfy(H(v["yb"]), Ya)
        isk_c = _isk(H(v["n_s_c"]), k_c, Ya, b"", Yb, b"") if k_c else None
        isk_s = _isk(H(v["n_s_s"]), k_s, Ya, b"", Yb, b"") if k_s else None
        c.eq(f"{n} isk_c", v["isk_c"], isk_c.hex() if isk_c else None)
        c.eq(f"{n} isk_s", v["isk_s"], isk_s.hex() if isk_s else None)
        c.true(f"{n} isk_c phải khác isk_s", isk_c != isk_s)
    else:  # wrong_pin
        g_c = calculate_generator(v["pin_c"].encode("utf-8"), b"HLBTPIN1", H(v["n_s"]))
        g_s = calculate_generator(v["pin_s"].encode("utf-8"), b"HLBTPIN1", H(v["n_s"]))
        c.true(f"{n} generator hai phía phải khác (PIN khác)", g_c != g_s)
        Ya, Yb = _scalar_mult_vfy(H(v["ya"]), g_c), _scalar_mult_vfy(H(v["yb"]), g_s)
        c.eq(f"{n} Ya", v["Ya"], Ya.hex() if Ya else None)
        c.eq(f"{n} Yb", v["Yb"], Yb.hex() if Yb else None)
        k_c, k_s = _scalar_mult_vfy(H(v["ya"]), Yb), _scalar_mult_vfy(H(v["yb"]), Ya)
        isk_c = _isk(H(v["n_s"]), k_c, Ya, b"", Yb, b"") if k_c else None
        isk_s = _isk(H(v["n_s"]), k_s, Ya, b"", Yb, b"") if k_s else None
        c.eq(f"{n} isk_c", v["isk_c"], isk_c.hex() if isk_c else None)
        c.eq(f"{n} isk_s", v["isk_s"], isk_s.hex() if isk_s else None)
        c.true(f"{n} isk_c phải khác isk_s (hoặc một phía abort)", isk_c is None or isk_s is None or isk_c != isk_s)


def check_cpace(c, doc: dict) -> None:
    kinds = set()
    for v in doc["vectors"]:
        n = f"cpace/{v['name']}"
        kinds.add(v["kind"])
        if v["kind"] == "official_generator":
            _check_official_generator(c, n, v)
        elif v["kind"] == "official_message":
            _check_official_message(c, n, v)
        elif v["kind"] == "handlive_pin":
            _check_handlive_pin(c, n, v)
        else:
            c.true(f"{n} kind {v['kind']!r} không nằm trong tập đã định", False)
    c.eq("cpace: có đủ loại vector", kinds, {"official_generator", "official_message", "handlive_pin"})
    for v in doc["invalid_vectors"]:
        _check_negative(c, f"cpace/{v['name']}", v)
    c.eq("cpace: đủ loại vector âm", {v["reason"] for v in doc["invalid_vectors"]}, REASONS)


CHECKS = {"cpace.json": check_cpace}
