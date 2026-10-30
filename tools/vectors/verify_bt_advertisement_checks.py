"""Kiểm bt-advertisement.json: dẫn lại K_bt_disc/hint bằng verify_common (hashlib/hmac, độc lập với
bt_link_derivations.py dùng `cryptography`); so khớp byte service_data và luật cửa sổ epoch bằng số học thuần.
"""
from verify_common import H, hkdf, hmac256

DISC_INFO = b"handlive/v1/bt-discovery"
HINT_LABEL = b"HLBTDISC1"
VER = 0x01
BT_ADV_MAX_HINTS = 2
BT_PIN_HINT = bytes(4)
REASONS = {"wrong_version", "hint_outside_window"}


def _hint(disc: bytes, epoch: int) -> bytes:
    return hmac256(disc, HINT_LABEL + epoch.to_bytes(8, "big", signed=True))[:4]


def _service_data(psm: int, hints: list) -> bytes:
    return bytes([VER]) + psm.to_bytes(2, "little") + b"".join(hints)


def _check_scan_response(c, n: str, v: dict) -> None:
    c.eq(f"{n} ver", v["ver"], f"0x{VER:02x}")
    c.true(f"{n} số hint ≤ BT_ADV_MAX_HINTS", len(v["hints"]) <= BT_ADV_MAX_HINTS)
    data = _service_data(v["psm"], [H(h) for h in v["hints"]])
    c.eq(f"{n} service_data_bytes", v["service_data_bytes"], data.hex())
    c.eq(f"{n} service_data_len", v["service_data_len"], len(data))
    c.eq(f"{n} scan_response_total = 18 + len(service_data)", v["scan_response_total"],
         v["ad_uuid_struct_bytes"] + len(data))


def _check_pin_window(c, n: str, v: dict) -> None:
    c.eq(f"{n} chỉ có BT_PIN_HINT", v["hints"], [BT_PIN_HINT.hex()])
    data = _service_data(v["psm"], [BT_PIN_HINT])
    c.eq(f"{n} service_data_bytes", v["service_data_bytes"], data.hex())


def _check_negative(c, n: str, v: dict, disc: bytes) -> None:
    reason = v["reason"]
    c.true(f"{n} reason nằm trong tập đã định", reason in REASONS)
    if reason == "wrong_version":
        data = H(v["service_data_bytes"])
        c.true(f"{n} byte đầu khác 0x01", data[0] != VER)
    else:
        advertised_hint = _hint(disc, v["advertised_epoch"])
        c.eq(f"{n} advertised_hint", v["advertised_hint"], advertised_hint.hex())
        diff = abs(v["advertised_epoch"] - v["client_epoch"])
        c.true(f"{n} kỷ nguyên cách client quá 4", diff > 4)
        c.eq(f"{n} accepted_epochs = [client-4..client+4]", v["accepted_epochs"],
             list(range(v["client_epoch"] - 4, v["client_epoch"] + 5)))
        c.true(f"{n} advertised_epoch không nằm trong accepted_epochs",
               v["advertised_epoch"] not in v["accepted_epochs"])


def check_bt_advertisement(c, doc: dict, all_docs: dict) -> None:
    link_doc = all_docs["bt-link.json"]
    prk_doc = all_docs["pair-prk.json"]
    pair1 = next(v for v in prk_doc["vectors"] if v["name"] == "cặp 1")
    disc = hkdf(H(pair1["prk"]), DISC_INFO, 32)
    key1 = next(v for v in link_doc["vectors"] if v["kind"] == "key" and v["name"] == "cặp 1")
    c.eq("bt-advertisement: K_bt_disc khớp bt-link.json", disc.hex(), key1["k_bt_disc"])

    kinds = set()
    for v in doc["vectors"]:
        n = f"bt-advertisement/{v['name']}"
        kinds.add(v["kind"])
        if v["kind"] == "scan_response":
            _check_scan_response(c, n, v)
        elif v["kind"] == "pin_window":
            _check_pin_window(c, n, v)
        else:
            c.true(f"{n} kind {v['kind']!r} không nằm trong tập đã định", False)
    c.eq("bt-advertisement: có đủ loại vector", kinds, {"scan_response", "pin_window"})
    for v in doc["invalid_vectors"]:
        _check_negative(c, f"bt-advertisement/{v['name']}", v, disc)
    c.eq("bt-advertisement: đủ loại vector âm", {v["reason"] for v in doc["invalid_vectors"]}, REASONS)


CHECKS = {"bt-advertisement.json": check_bt_advertisement}
