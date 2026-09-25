"""Dựng discovery-hint.json: K_disc và gợi ý mDNS theo giờ (00-common-specs.md 0.4.1; 03-connectivity.md CONN-01
bước 3, API 1–2) từ PRK của pair-prk.json.

- kind "key": K_disc của một cặp; gợi ý của từng chỉ số giờ, kể cả giờ −1 (giờ trước của giờ 0, int64 bù hai); với
  mỗi thời điểm now_ms: chỉ số giờ, gợi ý điện thoại quảng bá và hai gợi ý client chấp nhận (giờ này rồi giờ trước).
- kind "match": điện thoại có nhiều cặp quảng bá TXT h lúc phone_now_ms; client của một cặp duyệt lúc client_now_ms
  và phải thấy khớp, kể cả khi đồng hồ điện thoại chậm hơn qua mốc giờ.
Vector âm: TXT h mà client KHÔNG được coi là khớp — đồng hồ lệch ra ngoài cửa sổ hai giờ, hoặc gợi ý tính sai (thứ
tự byte, độ dài của chỉ số giờ, nhãn, khóa HMAC).
"""
import pairing_discovery_derivations as P

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
# Thời điểm (ms) của phần "clock": mốc giờ 0/1 và quanh mốc 1727150400000 (= giờ 479764).
CLOCK = [0, 3_599_999, 3_600_000, 1_727_150_000_123, 1_727_150_399_999, 1_727_150_400_000]
# (tên, cặp của điện thoại theo thứ tự trong TXT h, phone_now_ms, cặp của client, client_now_ms)
MATCHES = [
    ("khớp giờ hiện tại, TXT h có gợi ý của hai cặp", ["cặp 1", "cặp 2"], 1_727_150_000_123, "cặp 1",
     1_727_150_000_123),
    ("điện thoại chậm hơn qua mốc giờ: khớp gợi ý giờ trước", ["cặp 2", "cặp 1"], 1_727_150_399_999, "cặp 2",
     1_727_150_400_000),
]


def _hint_row(key: bytes, hour: int) -> dict:
    msg = P.discovery_message(hour)
    return {"hour": hour, "message": msg.hex(), "mac": P.hmac_sha256(key, msg).hex(), "hint": P.discovery_hint(key, hour)}


def _accepted(key: bytes, now_ms: int) -> list[str]:
    hour = P.hour_index(now_ms)
    return [P.discovery_hint(key, hour), P.discovery_hint(key, hour - 1)]


def _key_vector(pv: dict, key: bytes) -> dict:
    hours = sorted({h for now in CLOCK for h in (P.hour_index(now), P.hour_index(now) - 1)})
    clock = [{"now_ms": now, "hour": P.hour_index(now), "advertised": P.discovery_hint(key, P.hour_index(now)),
              "accepted": _accepted(key, now)} for now in CLOCK]
    return {"name": pv["name"], "kind": "key", "pair_id": pv["pair_id"], "prk_source": "pair-prk.json",
            "prk": pv["prk"], "info": P.DISCOVERY_INFO, "length": 32, "k_disc": key.hex(),
            "hours": [_hint_row(key, h) for h in hours], "clock": clock}


def _match_vector(keys: dict, name, phone_pairs, phone_now, client_pair, client_now) -> dict:
    txt = [P.discovery_hint(keys[p], P.hour_index(phone_now)) for p in phone_pairs]
    accepted = _accepted(keys[client_pair], client_now)
    hit = [h for h in accepted if h in txt]
    assert len(hit) == 1, name
    return {"name": name, "kind": "match", "phone_pairs": phone_pairs, "phone_now_ms": phone_now,
            "phone_hour": P.hour_index(phone_now), "txt_h": ",".join(txt), "client_pair": client_pair,
            "client_now_ms": client_now, "client_hour": P.hour_index(client_now), "accepted": accepted,
            "matched_hint": hit[0], "matched_as": "current" if hit[0] == accepted[0] else "previous"}


def _negative(name, pair, reason, client_now, txt_h, **proof) -> dict:
    v = {"name": f"{pair} / {name}", "pair": pair, "reason": reason, "client_now_ms": client_now,
         "client_hour": P.hour_index(client_now), "txt_h": txt_h}
    v.update({k: x.hex() if isinstance(x, bytes) else x for k, x in proof.items()})
    return v


def _negatives(keys: dict, prks: dict) -> list[dict]:
    k1, k2 = keys["cặp 1"], keys["cặp 2"]
    now = 1_727_150_000_123
    hour = P.hour_index(now)
    out = []
    for name, phone_now, client_now in (("đồng hồ điện thoại nhanh hơn, đã qua mốc giờ", 1_727_150_400_000,
                                         1_727_150_399_999),
                                        ("gợi ý cũ hai giờ", 1_727_143_200_000, 1_727_150_400_000)):
        out.append(_negative(name, "cặp 1", "hint_outside_window", client_now,
                             P.discovery_hint(k1, P.hour_index(phone_now)), phone_now_ms=phone_now,
                             phone_hour=P.hour_index(phone_now)))
    for name, pair, key, reason, mistake in (
            ("chỉ số giờ viết int64 little-endian", "cặp 1", k1, "wrong_byte_order", {"int_format": "<q"}),
            ("chỉ số giờ viết int32 big-endian (4 byte)", "cặp 2", k2, "wrong_encoding", {"int_format": ">i"}),
            ("nhãn \"HLDISC1|\" thêm dấu |", "cặp 2", k2, "wrong_label", {"label": b"HLDISC1|"})):
        msg = P.discovery_message(hour, **mistake)
        out.append(_negative(name, pair, reason, now, P.first_hex8(P.hmac_sha256(key, msg)), message=msg))
    prk = prks["cặp 1"]
    msg = P.discovery_message(hour)
    out.append(_negative("HMAC khóa bằng PRK thay vì K_disc", "cặp 1", "wrong_key", now,
                         P.first_hex8(P.hmac_sha256(prk, msg)), mac_key=prk, message=msg))
    return out


DESCRIPTION = (
    "Gợi ý mDNS (TXT h) theo giờ. K_disc = HKDF-SHA256(PRK, salt rỗng, info \"handlive/v1/discovery\", L 32); "
    "giờ = floor(now_ms / 3 600 000) (làm tròn xuống, kể cả số âm); hint = 8 chữ số hex thường đầu của "
    "HMAC-SHA256(K_disc, \"HLDISC1\" ‖ giờ int64 BE). Điện thoại quảng bá gợi ý giờ hiện tại của mỗi cặp (≤ 8, nối "
    "bằng dấu phẩy, không dấu cách); client chấp nhận gợi ý của giờ hiện tại VÀ giờ trước theo đồng hồ của nó "
    "(accepted = [giờ này, giờ trước]). kind \"key\": K_disc, gợi ý từng giờ, và theo từng now_ms; kind \"match\": TXT "
    "h phải khớp. Vector âm: TXT h không được coi là khớp (đồng hồ lệch ngoài cửa sổ, hoặc gợi ý tính sai).")


def build(ctx: dict) -> dict:
    prks = {v["name"]: H(v["prk"]) for v in ctx["pairs"]}
    keys = {name: P.discovery_key(prk) for name, prk in prks.items()}
    vectors = [_key_vector(pv, keys[pv["name"]]) for pv in ctx["pairs"]]
    vectors += [_match_vector(keys, *m) for m in MATCHES]
    doc = {"description": DESCRIPTION,
           "source": f"{SPEC} 0.4.1; docs/detailed-design/03-connectivity.md CONN-01 bước 3, API 1–2; PRK của "
                     "pair-prk.json",
           "vectors": vectors, "invalid_vectors": _negatives(keys, prks)}
    return {"discovery-hint.json": doc}
