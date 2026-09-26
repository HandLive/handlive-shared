"""Bản rõ JSON và envelope của các thông điệp `pair` (02-pairing.md PAIR-01 API 2–6) cho vector pair-handshake.json.

`s` là trạng thái thô của một lần ghép nối do build_pair_handshake_vectors._state dựng. Thứ tự khóa JSON theo bảng
của spec; JSON không bao giờ được ký hay MAC, bên nhận parse thay vì so chuỗi.
"""
import pairing_discovery_derivations as P
from handlive_protocol_derivations import b64, b64u, compact_json, envelope_wire

# Thời điểm gửi (ms) của từng thông điệp tính từ created_at (confirm gửi đúng lúc created_at).
MESSAGE_OFFSETS = {"hello": -2210, "offer": -2170, "confirm": 0, "done": 45, "error": -2100}


def plaintext(op: str, data: dict) -> str:
    return compact_json({"op": op, "data": data})


def envelope(s: dict, op: str, pt: str) -> str:
    """Envelope `type = pair`, payload = b64 của bản rõ (không mã hóa, 0.5.1 ngoại lệ 1), id UUIDv7 tất định."""
    ts = s["created_at"] + MESSAGE_OFFSETS[op]
    return envelope_wire(1, "pair", P.uuid7(ts, f"{s['name']} {op}"), ts, b64(pt.encode()))


def hello_data(s: dict, **over) -> dict:
    d = {"mode": s["mode"], "device_id": s["c_id"], "nonce": b64u(s["nonce_c"]), "name": s["c_name"],
         "platform": s["c_platform"], "model": s["c_model"], "ik_sig_pub": b64u(s["c_pub"]),
         "ik_dh_pub": b64u(s["c_dh_pub"])}
    return {**d, **over}


def offer_data(s: dict, **over) -> dict:
    d = {"device_id": s["a_id"], "nonce": b64u(s["nonce_s"]), "name": s["a_name"], "model": s["a_model"],
         "os_version": s["a_os"], "ik_sig_pub": b64u(s["a_pub"]), "ik_dh_pub": b64u(s["a_dh_pub"]),
         "tls_sha256": b64u(s["tls"]), "mac": b64u(s["offer_mac"])}
    return {**d, **over}


def confirm_data(s: dict, **over) -> dict:
    d = {"pair_id": s["pair_id"], "created_at": s["created_at"], "sig": b64u(s["sig_c"]),
         "prk_check": b64u(s["prk_check_c"]), "mac": b64u(s["confirm_mac"])}
    return {**d, **over}


def done_data(s: dict, **over) -> dict:
    d = {"sig": b64u(s["sig_s"]), "prk_check": b64u(s["prk_check_s"]), "mac": b64u(s["done_mac"])}
    return {**d, **over}


DATA = {"hello": hello_data, "offer": offer_data, "confirm": confirm_data, "done": done_data}


def message(s: dict, op: str, **over) -> tuple[str, str]:
    """(bản rõ, envelope) của pair/<op> với các trường `over` thay giá trị đúng."""
    pt = plaintext(op, DATA[op](s, **over))
    return pt, envelope(s, op, pt)
