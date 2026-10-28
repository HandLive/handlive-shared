"""Dựng bt-advertisement.json: byte service data mà app tự kiểm soát trong scan response (0.4.5 "Advertisement") —
`ver` ‖ `psm` (uint16 LE) ‖ `hints` (4 × n, n ≤ BT_ADV_MAX_HINTS); hệ điều hành tự thêm phần còn lại của cấu trúc
AD (cờ, UUID 128-bit) nên không thuộc phạm vi vector này (xem #3337: service_data_bytes log 11, cộng 18 của OS
mới ra 29). Cộng `BT_PIN_HINT` khi đang mở cửa sổ ghép đôi PIN, và mẫu âm cho luật khớp hint ở client.
"""
import bt_link_derivations as BT

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
BT_ADV_MAX_HINTS = 2
BT_PIN_HINT = bytes(4)
AD_UUID_STRUCT_BYTES = 18  # AD length + AD type + UUID 128-bit, hệ điều hành tự thêm
VER = 0x01


def _service_data(psm: int, hints: list) -> bytes:
    return bytes([VER]) + psm.to_bytes(2, "little") + b"".join(hints)


def _scan_response_vector(name: str, psm: int, hints: list, pair_names: list) -> dict:
    data = _service_data(psm, hints)
    total = AD_UUID_STRUCT_BYTES + len(data)
    return {"name": name, "kind": "scan_response", "ver": f"0x{VER:02x}", "psm": psm, "psm_hex": psm.to_bytes(2, "little").hex(),
            "hints": [h.hex() for h in hints], "hint_pairs": pair_names, "service_data_bytes": data.hex(),
            "service_data_len": len(data), "ad_uuid_struct_bytes": AD_UUID_STRUCT_BYTES,
            "scan_response_total": total, "note": f"service_data_bytes = phần app tự kiểm soát; OS thêm "
            f"{AD_UUID_STRUCT_BYTES} byte UUID/cờ nữa mới ra tổng {total} byte"}


def _negatives(disc: bytes) -> list[dict]:
    out = []
    data = _service_data(23456, [BT.disc_hint(disc, 1000)])
    bad_ver = bytearray(data)
    bad_ver[0] = 0x02
    out.append({"name": "ver khác 0x01", "reason": "wrong_version", "service_data_bytes": bytes(bad_ver).hex(),
                "expect": "ver = 0x02 ≠ 0x01 → client bỏ qua toàn bộ advertisement, không xét hint"})

    client_epoch = 1000
    accepted = list(range(client_epoch - 4, client_epoch + 5))
    outside_epoch = client_epoch + 5
    outside_hint = BT.disc_hint(disc, outside_epoch)
    out.append({"name": "hint ngoài cửa sổ e-4..e+4", "reason": "hint_outside_window",
                "client_epoch": client_epoch, "accepted_epochs": accepted, "advertised_epoch": outside_epoch,
                "advertised_hint": outside_hint.hex(), "service_data_bytes": _service_data(23456, [outside_hint]).hex(),
                "expect": f"advertised_epoch = {outside_epoch} cách client_epoch {outside_epoch - client_epoch} kỷ "
                          "nguyên, ngoài [e-4, e+4] → client không thấy khớp hint nào"})
    return out


DESCRIPTION = (
    "Byte service data app tự kiểm soát trong scan response (0.4.5 \"Advertisement\"): `ver` (1, luôn 0x01) ‖ "
    "`psm` (2, uint16 LE, PSM L2CAP hiện tại) ‖ `hints` (4 × n, n = 0…BT_ADV_MAX_HINTS = 2, mỗi hint = 4 byte đầu "
    "của HMAC-SHA256(K_bt_disc, \"HLBTDISC1\" ‖ epoch int64 BE)) — K_bt_disc/hint lấy từ bt-link.json. OS thêm 18 "
    "byte cấu trúc AD (cờ + UUID 128-bit) để ra tổng scan response (21/25/29 byte cho n=0/1/2) — không thuộc "
    "phạm vi vector này, chỉ ghi `scan_response_total` để đối chiếu bảng 0.4.5. `kind` = \"pin_window\": `hints` "
    "= chỉ `BT_PIN_HINT` (0x00000000), đánh dấu cửa sổ ghép đôi PIN đang mở, giống nhau cho mọi điện thoại (AC9). "
    "invalid_vectors: wrong_version (ver ≠ 0x01 → bỏ qua cả advertisement), hint_outside_window (hint tính ở kỷ "
    "nguyên ngoài [e-4, e+4] của client → không khớp)."
)


def build(ctx: dict, files: dict) -> dict:
    link_doc = files["bt-link.json"]
    key_vectors = [v for v in link_doc["vectors"] if v["kind"] == "key"]
    disc = H(next(v for v in key_vectors if v["name"] == "cặp 1")["k_bt_disc"])
    disc2 = H(next(v for v in key_vectors if v["name"] == "cặp 2")["k_bt_disc"])

    psm = 23456
    hint1, hint2 = BT.disc_hint(disc, 2000), BT.disc_hint(disc2, 2000)
    vectors = [
        _scan_response_vector("0 hint (không cặp nào có session nào, không có cửa sổ QR)", psm, [], []),
        _scan_response_vector("1 hint (một cặp gần đây nhất)", psm, [hint1], ["cặp 1"]),
        _scan_response_vector("2 hint (BT_ADV_MAX_HINTS, hai cặp gần đây nhất)", psm, [hint1, hint2],
                               ["cặp 1", "cặp 2"]),
        {"name": "cửa sổ PIN đang mở (BT_PIN_HINT)", "kind": "pin_window", "ver": f"0x{VER:02x}", "psm": psm,
         "psm_hex": psm.to_bytes(2, "little").hex(), "hints": [BT_PIN_HINT.hex()],
         "service_data_bytes": _service_data(psm, [BT_PIN_HINT]).hex(),
         "service_data_len": len(_service_data(psm, [BT_PIN_HINT])),
         "note": "BT_PIN_HINT giống nhau cho mọi điện thoại, không gắn với cặp hay thiết bị nào (AC9)"},
    ]
    negatives = _negatives(disc)
    doc = {"description": DESCRIPTION,
           "source": f"{SPEC} 0.4.5 \"Advertisement\"; K_bt_disc của bt-link.json",
           "vectors": vectors, "invalid_vectors": negatives}
    return {"bt-advertisement.json": doc}
