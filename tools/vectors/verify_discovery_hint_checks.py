"""Kiểm discovery-hint.json bằng hashlib/hmac (verify_common), độc lập với phía sinh (`cryptography`).

Giờ = now_ms // 3 600 000 (phép chia của Python làm tròn xuống, đúng cả với số âm); thông điệp = "HLDISC1" ‖ giờ
int64 BE; hint = hex thường của 4 byte đầu HMAC-SHA256(K_disc, thông điệp). Client chấp nhận [giờ trước, giờ này, giờ
sau] theo đồng hồ của nó (0.4.1, chịu lệch tới một giờ theo cả hai chiều); TXT h là danh sách hint nối bằng dấu phẩy.
"""
import re
import struct

from verify_common import H, hkdf, hmac256

HOUR_MS = 3_600_000
REASONS = {"hint_outside_window", "wrong_byte_order", "wrong_encoding", "wrong_label", "wrong_key"}
WINDOW = {-1: "previous", 0: "current", 1: "next"}


def k_disc(prk: bytes) -> bytes:
    return hkdf(prk, b"handlive/v1/discovery", 32)


def message(hour: int) -> bytes:
    return b"HLDISC1" + struct.pack(">q", hour)


def hint(key: bytes, hour: int) -> str:
    return hmac256(key, message(hour))[:4].hex()


def accepted(key: bytes, now_ms: int) -> list[str]:
    hour = now_ms // HOUR_MS
    return [hint(key, hour + d) for d in WINDOW]


def _check_key(c, n: str, v: dict, pair_prk: dict) -> None:
    pv = pair_prk[v["name"]]
    c.eq(f"{n} prk và pair_id lấy từ pair-prk.json", (v["prk_source"], v["prk"], v["pair_id"]),
         ("pair-prk.json", pv["prk"], pv["pair_id"]))
    key = k_disc(H(v["prk"]))
    c.eq(f"{n} K_disc", (v["info"], v["length"], v["k_disc"]), ("handlive/v1/discovery", 32, key.hex()))
    for row in v["hours"]:
        msg = message(row["hour"])
        c.eq(f"{n} giờ {row['hour']}", (row["message"], row["mac"], row["hint"]),
             (msg.hex(), hmac256(key, msg).hex(), hint(key, row["hour"])))
        c.true(f"{n} giờ {row['hour']}: hint là 8 hex thường", re.fullmatch(r"[0-9a-f]{8}", row["hint"]) is not None)
    for row in v["clock"]:
        hour = row["now_ms"] // HOUR_MS
        c.eq(f"{n} now_ms {row['now_ms']}", (row["hour"], row["advertised"], row["accepted"]),
             (hour, hint(key, hour), accepted(key, row["now_ms"])))
    nows = {row["now_ms"] for row in v["clock"]}
    c.true(f"{n} có cặp thời điểm sát mốc giờ", any(t % HOUR_MS == 0 and t - 1 in nows for t in nows if t > 0))
    c.true(f"{n} có giờ −1 (giờ trước của giờ 0)", -1 in {row["hour"] for row in v["hours"]})


def _check_match(c, n: str, v: dict, keys: dict) -> None:
    phone_hour = v["phone_now_ms"] // HOUR_MS
    txt = [hint(keys[p], phone_hour) for p in v["phone_pairs"]]
    acc = accepted(keys[v["client_pair"]], v["client_now_ms"])
    c.eq(f"{n} TXT h do điện thoại quảng bá", (v["phone_hour"], v["txt_h"]), (phone_hour, ",".join(txt)))
    c.eq(f"{n} client chấp nhận", (v["client_hour"], v["accepted"]), (v["client_now_ms"] // HOUR_MS, acc))
    hits = [h for h in acc if h in v["txt_h"].split(",")]
    c.eq(f"{n} khớp đúng một gợi ý", hits, [v["matched_hint"]])
    c.eq(f"{n} matched_as theo chênh lệch giờ", v["matched_as"], WINDOW.get(phone_hour - v["client_now_ms"] // HOUR_MS))


def _check_negative(c, n: str, v: dict, keys: dict, prks: dict) -> None:
    key, hour = keys[v["pair"]], v["client_now_ms"] // HOUR_MS
    c.eq(f"{n} client_hour", v["client_hour"], hour)
    c.true(f"{n} client KHÔNG được coi là khớp", not set(v["txt_h"].split(",")) & set(accepted(key, v["client_now_ms"])))
    reason = v["reason"]
    if reason == "hint_outside_window":
        phone_hour = v["phone_now_ms"] // HOUR_MS
        c.eq(f"{n} TXT h = gợi ý điện thoại quảng bá", (v["phone_hour"], v["txt_h"]), (phone_hour, hint(key, phone_hour)))
        c.eq(f"{n} giờ của điện thoại cách giờ của client hai giờ", abs(phone_hour - hour), 2)
        return
    wrong = {"wrong_byte_order": b"HLDISC1" + struct.pack("<q", hour),
             "wrong_encoding": b"HLDISC1" + struct.pack(">i", hour),
             "wrong_label": b"HLDISC1|" + struct.pack(">q", hour),
             "wrong_key": message(hour)}.get(reason)
    if wrong is None:
        c.true(f"{n} reason {reason!r} không nằm trong tập đã định", False)
        return
    mac_key = prks[v["pair"]] if reason == "wrong_key" else key
    c.eq(f"{n} message dựng đúng lỗi", H(v["message"]), wrong)
    if reason == "wrong_key":
        c.eq(f"{n} mac_key = PRK", H(v["mac_key"]), mac_key)
    c.eq(f"{n} TXT h = hint tính sai", v["txt_h"], hmac256(mac_key, wrong)[:4].hex())


def check_discovery_hint(c, doc, all_docs):
    pair_prk = {v["name"]: v for v in all_docs["pair-prk.json"]["vectors"]}
    prks = {name: H(v["prk"]) for name, v in pair_prk.items()}
    keys = {name: k_disc(prk) for name, prk in prks.items()}
    kinds = {}
    for v in doc["vectors"]:
        n = f"discovery-hint/{v['name']}"
        kinds.setdefault(v["kind"], []).append(v)
        if v["kind"] == "key":
            _check_key(c, n, v, pair_prk)
        elif v["kind"] == "match":
            _check_match(c, n, v, keys)
        else:
            c.true(f"{n} kind {v['kind']!r} không nằm trong tập đã định", False)
    c.eq("discovery-hint: mỗi cặp của pair-prk.json có một vector key", sorted(v["name"] for v in kinds.get("key", [])),
         sorted(pair_prk))
    matches = kinds.get("match", [])
    c.eq("discovery-hint: có khớp giờ trước, giờ này và giờ sau", {v["matched_as"] for v in matches}, set(WINDOW.values()))
    skews = {v["phone_now_ms"] - v["client_now_ms"] for v in matches if v["phone_hour"] != v["client_hour"]}
    c.true("discovery-hint: đồng hồ điện thoại nhanh và chậm 1 ms và đúng một giờ qua mốc giờ",
           {-HOUR_MS, -1, 1, HOUR_MS} <= skews)
    for v in doc["invalid_vectors"]:
        _check_negative(c, f"discovery-hint/{v['name']}", v, keys, prks)
    c.eq("discovery-hint: đủ loại vector âm", {v["reason"] for v in doc["invalid_vectors"]}, REASONS)
    outside = {v["phone_hour"] - v["client_hour"] for v in doc["invalid_vectors"] if v["reason"] == "hint_outside_window"}
    c.eq("discovery-hint: điện thoại nhanh và chậm hai giờ", outside, {-2, 2})


CHECKS = {"discovery-hint.json": check_discovery_hint}
