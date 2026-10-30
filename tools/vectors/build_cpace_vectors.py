"""Dựng cpace.json: vector chính thức của draft-irtf-cfrg-cpace-21 (CPACE-X25519-SHA512, Appendix B.1), rồi các
case theo cách HandLive dùng (PIN qua Bluetooth không mạng, 00-common-specs.md 0.4.5 luồng C): `g`, `Ya`, `Yb`,
`K`, `ISK`, `K_bt_pinlink`, `K_bt_pin`; cộng mẫu âm (Ya/Yb bậc thấp, sid khác, PIN sai).
"""
import cpace_pin_derivations as PIN
import cpace_x25519_sha512 as C
from cpace_source_values import (
    CPACE_X25519_SHA512_GENERATOR as SRC_GEN,
    CPACE_X25519_SHA512_LOW_ORDER_POINTS as SRC_LOW_POINTS,
    CPACE_X25519_SHA512_MESSAGE as SRC_MSG,
)
from handlive_protocol_derivations import test_bytes

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
DRAFT = "draft-irtf-cfrg-cpace-21"
HL_CI = b"HLBTPIN1"


def _official_generator_vector() -> dict:
    prs, ci, sid = H(SRC_GEN["PRS"]), H(SRC_GEN["CI"]), H(SRC_GEN["sid"])
    g = C.calculate_generator(prs, ci, sid)
    assert g == H(SRC_GEN["generator g"]), "calculate_generator phải khớp Appendix B.1.1 của draft"
    return {"name": "draft B.1.1 calculate_generator", "kind": "official_generator", "draft": DRAFT,
            "section": "Appendix B.1.1", "H": SRC_GEN["H"], "PRS": SRC_GEN["PRS"], "CI": SRC_GEN["CI"],
            "sid": SRC_GEN["sid"], "generator_string": SRC_GEN["generator_string(G.DSI,PRS,CI,sid,H.s_in_bytes)"],
            "hash_generator_string": SRC_GEN["hash generator string"],
            "decoded_field_element": SRC_GEN["decoded field element of 255 bits"], "g": g.hex()}


def _official_message_vector() -> dict:
    prs, ci, sid = H(SRC_MSG["PRS"]), H(SRC_MSG["CI"]), H(SRC_MSG["sid"])
    ya, ADa, yb, ADb = H(SRC_MSG["ya"]), H(SRC_MSG["ADa"]), H(SRC_MSG["yb"]), H(SRC_MSG["ADb"])
    r = C.run_both_sides(prs, ci, sid, ya, ADa, yb, ADb)
    assert r["g"] == H(SRC_MSG["g"])
    assert r["Ya"] == H(SRC_MSG["Ya"]) and r["Yb"] == H(SRC_MSG["Yb"])
    assert r["k_a"] == H(SRC_MSG["K"]) == r["k_b"]
    assert r["isk_a"] == H(SRC_MSG["ISK_IR"]) == r["isk_b"]
    return {"name": "draft B.1.2-B.1.7 message A/B, K, ISK", "kind": "official_message", "draft": DRAFT,
            "section": "Appendix B.1.2-B.1.7", "PRS": SRC_MSG["PRS"], "CI": SRC_MSG["CI"], "sid": SRC_MSG["sid"],
            "g": r["g"].hex(), "ya": SRC_MSG["ya"], "ADa": SRC_MSG["ADa"], "Ya": r["Ya"].hex(), "yb": SRC_MSG["yb"],
            "ADb": SRC_MSG["ADb"], "Yb": r["Yb"].hex(), "K": r["k_a"].hex(), "ISK_initiator_responder": r["isk_a"].hex(),
            "ISK_parallel_source": SRC_MSG["ISK_SY"],
            "note": "ISK_parallel_source là biến thể song hành (transcript_oc) công bố trong draft; HandLive chỉ "
                    "dùng khởi tạo/trả lời (transcript_ir, ISK_initiator_responder) vì C luôn khởi tạo và S luôn "
                    "trả lời (0.4.5 luồng C)."}


def _handlive_pin_vector(name: str, pin: str) -> dict:
    prs = pin.encode("utf-8")
    n_s = test_bytes(f"cpace pin n_s {name}", 32)
    ya = test_bytes(f"cpace pin ya {name}", 32)
    yb = test_bytes(f"cpace pin yb {name}", 32)
    r = C.run_both_sides(prs, HL_CI, n_s, ya, b"", yb, b"")
    assert r["k_a"] is not None and r["k_a"] == r["k_b"], f"{name}: K phải khớp cả hai phía"
    assert r["isk_a"] == r["isk_b"]
    isk = r["isk_a"]
    pinlink, pinpair = PIN.k_bt_pinlink(isk, n_s), PIN.k_bt_pin(isk, n_s)
    return {"name": name, "kind": "handlive_pin", "pin": pin, "ci": HL_CI.decode(), "n_s": n_s.hex(),
            "ya": ya.hex(), "yb": yb.hex(), "g": r["g"].hex(), "Ya": r["Ya"].hex(), "Yb": r["Yb"].hex(),
            "K": r["k_a"].hex(), "ISK": isk.hex(), "k_bt_pinlink_info": PIN.PINLINK_INFO.decode(),
            "k_bt_pinlink": pinlink.hex(), "k_bt_pin_info": PIN.PIN_INFO.decode(), "k_bt_pin": pinpair.hex()}


def _negative_low_order(name: str, side: str) -> dict:
    """side = "ya": C (khởi tạo) gửi Ya bậc thấp, S phải abort. side = "yb": S (trả lời) gửi Yb bậc thấp, C phải
    abort. Dùng điểm u0 của draft (Appendix B.1.10, bất kể vô hướng — đã kiểm bằng vô hướng cố định của draft và
    một vô hướng HandLive khác, cùng kết quả abort)."""
    pin = "482917"
    prs = pin.encode("utf-8")
    n_s = test_bytes(f"cpace neg low_order {side} n_s", 32)
    g = C.calculate_generator(prs, HL_CI, n_s)
    low_u = H(SRC_LOW_POINTS[0]["u"])  # u0 = zero_bytes — luôn trong tập "MUST trigger abort"
    assert SRC_LOW_POINTS[0]["must_abort"]
    if side == "ya":
        yb = test_bytes(f"cpace neg low_order {side} yb", 32)
        Yb = C.scalar_mult_vfy(yb, g)
        k_s = C.scalar_mult_vfy(yb, low_u)
        assert k_s is None
        return {"name": name, "reason": "low_order_ya", "pin": pin, "n_s": n_s.hex(), "g": g.hex(),
                "Ya_attacker": low_u.hex(), "yb": yb.hex(), "Yb": Yb.hex(),
                "expect": "S (trả lời) tính K = scalar_mult_vfy(yb, Ya) → None (G.I) → đóng kênh không trả lời"}
    ya = test_bytes(f"cpace neg low_order {side} ya", 32)
    Ya = C.scalar_mult_vfy(ya, g)
    k_c = C.scalar_mult_vfy(ya, low_u)
    assert k_c is None
    return {"name": name, "reason": "low_order_yb", "pin": pin, "n_s": n_s.hex(), "g": g.hex(), "ya": ya.hex(),
            "Ya": Ya.hex(), "Yb_attacker": low_u.hex(),
            "expect": "C (khởi tạo) tính K = scalar_mult_vfy(ya, Yb) → None (G.I) → đóng kênh không trả lời"}


def _negative_sid_mismatch(name: str) -> dict:
    pin = "482917"
    prs = pin.encode("utf-8")
    n_s_c = test_bytes("cpace neg sid_mismatch n_s_c", 32)
    n_s_s = test_bytes("cpace neg sid_mismatch n_s_s", 32)
    assert n_s_c != n_s_s
    ya = test_bytes("cpace neg sid_mismatch ya", 32)
    yb = test_bytes("cpace neg sid_mismatch yb", 32)
    g_c, g_s = C.calculate_generator(prs, HL_CI, n_s_c), C.calculate_generator(prs, HL_CI, n_s_s)
    Ya, Yb = C.scalar_mult_vfy(ya, g_c), C.scalar_mult_vfy(yb, g_s)
    k_c, k_s = C.scalar_mult_vfy(ya, Yb), C.scalar_mult_vfy(yb, Ya)
    isk_c = C.isk(n_s_c, k_c, Ya, b"", Yb, b"") if k_c else None
    isk_s = C.isk(n_s_s, k_s, Ya, b"", Yb, b"") if k_s else None
    assert isk_c is not None and isk_s is not None and isk_c != isk_s, "sid khác nhau phải cho ISK khác nhau"
    return {"name": name, "reason": "sid_mismatch", "pin": pin, "n_s_c": n_s_c.hex(), "n_s_s": n_s_s.hex(),
            "ya": ya.hex(), "yb": yb.hex(), "Ya": Ya.hex(), "Yb": Yb.hex(), "isk_c": isk_c.hex(),
            "isk_s": isk_s.hex(),
            "expect": "C dùng sid của mình, S dùng sid của mình (hai kênh khác nhau trộn vào) → ISK hai phía "
                      "khác nhau (isk_c != isk_s), K_bt_pinlink suy từ đó cũng khác → noise1 của S không mở được"}


def _negative_wrong_pin(name: str) -> dict:
    n_s = test_bytes("cpace neg wrong_pin n_s", 32)
    pin_c, pin_s = "482917", "482918"
    ya = test_bytes("cpace neg wrong_pin ya", 32)
    yb = test_bytes("cpace neg wrong_pin yb", 32)
    g_c = C.calculate_generator(pin_c.encode(), HL_CI, n_s)
    g_s = C.calculate_generator(pin_s.encode(), HL_CI, n_s)
    assert g_c != g_s, "PIN khác phải cho generator khác"
    Ya, Yb = C.scalar_mult_vfy(ya, g_c), C.scalar_mult_vfy(yb, g_s)
    k_c, k_s = C.scalar_mult_vfy(ya, Yb), C.scalar_mult_vfy(yb, Ya)
    isk_c = C.isk(n_s, k_c, Ya, b"", Yb, b"") if k_c else None
    isk_s = C.isk(n_s, k_s, Ya, b"", Yb, b"") if k_s else None
    assert isk_c is None or isk_s is None or isk_c != isk_s, "PIN khác phải cho ISK khác (hoặc abort)"
    return {"name": name, "reason": "wrong_pin", "n_s": n_s.hex(), "pin_c": pin_c, "pin_s": pin_s, "ya": ya.hex(),
            "yb": yb.hex(), "Ya": Ya.hex(), "Yb": Yb.hex(), "isk_c": isk_c.hex() if isk_c else None,
            "isk_s": isk_s.hex() if isk_s else None,
            "expect": "PIN gõ sai ở một phía → generator khác nhau → ISK hai phía khác nhau (hoặc K toàn 0) → "
                      "noise1 dùng K_bt_pinlink sai không mở được, một lần thử bị tính vào bộ đếm chung"}


DESCRIPTION = (
    "CPACE-X25519-SHA512 (draft-irtf-cfrg-cpace-21, suite G_X25519 + SHA-512). kind \"official_generator\"/"
    "\"official_message\": vector công bố của draft (Appendix B.1), chép nguyên văn qua cpace_source_values.py, "
    "dùng để kiểm cài đặt calculate_generator/Ya/Yb/K/ISK đúng thuật toán trước khi áp case của HandLive. kind "
    "\"handlive_pin\": ghép đôi bằng PIN qua Bluetooth không mạng (0.4.5 luồng C) — PRS = UTF-8 của 6 chữ số PIN "
    "(giữ số 0 đứng đầu), CI = \"HLBTPIN1\" cố định, sid = n_s (32 byte, mới cho mỗi kênh), ADa = ADb rỗng; C "
    "khởi tạo (cpace1 = Ya), S trả lời (cpace2 = Yb); K_bt_pinlink/K_bt_pin = HKDF-SHA256(ikm = ISK, salt = n_s, "
    "info tương ứng, L 32). invalid_vectors: low_order_ya/low_order_yb (bên kia nhận một điểm bậc thấp của "
    "Appendix B.1.10 → K = G.I → phải đóng kênh không trả lời, đúng \"an all-zero K → close without answer\" của "
    "0.4.5), sid_mismatch (hai phía dùng n_s khác nhau → ISK khác nhau), wrong_pin (PIN gõ sai một phía → "
    "generator khác nhau → ISK khác nhau hoặc K toàn 0) — cả hai trường hợp sau không bị CPace tự abort, chỉ lộ "
    "ra khi noise1 (psk = K_bt_pinlink) không mở được ở bước ghép đôi tiếp theo (bt-pairing.json, chưa nối case "
    "PIN vào — còn một việc để làm sau)."
)


def build() -> dict:
    official = [_official_generator_vector(), _official_message_vector()]
    handlive = [
        _handlive_pin_vector("HandLive PIN 482917", "482917"),
        _handlive_pin_vector("HandLive PIN với số 0 đứng đầu", "007042"),
    ]
    negatives = [
        _negative_low_order("Ya bậc thấp (C gửi điểm bậc thấp)", "ya"),
        _negative_low_order("Yb bậc thấp (S trả lời điểm bậc thấp)", "yb"),
        _negative_sid_mismatch("sid khác nhau giữa C và S"),
        _negative_wrong_pin("PIN sai ở một phía"),
    ]
    doc = {"description": DESCRIPTION,
           "source": f"{DRAFT} Appendix B.1 (CPACE-X25519-SHA512); {SPEC} 0.4.5 \"PIN (PAIR-01 flow C)\", "
                     "\"Keys from ISK\"",
           "vectors": official + handlive, "invalid_vectors": negatives}
    return {"cpace.json": doc}
