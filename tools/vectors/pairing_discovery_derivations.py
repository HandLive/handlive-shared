"""Phép dẫn xuất PAIR-01, PAIR-02 và gợi ý mDNS dùng để SINH vector.

Nguồn: 02-pairing.md PAIR-01 API 1–8 và PAIR-02 trường 10; 00-common-specs.md 0.4.1, 0.6.2; 03-connectivity.md
CONN-01 API 1–2. Phía sinh chỉ dùng `cryptography` (SHA-256, HMAC, HKDF, Argon2id của OpenSSL, X25519, Ed25519);
phía kiểm (verify_pair_handshake_checks.py, verify_discovery_hint_checks.py) cài lại bằng hashlib/hmac, libsodium
(pynacl) và argon2-cffi (bản C tham chiếu của PHC), không dùng chung mã với file này.

Bố cục byte (chỗ spec không nói rõ thì theo lựa chọn của bản Android, ghi trong shared/test-vectors/README.md):
- nhãn là ASCII, không dấu cách: "HL1|offer|", "HL1|confirm|", "HL1|done|", "HL1|prk-check-c|", "HL1|prk-check-s|",
  "HLPAIR1", "HLDISC1";
- uuid = 16 byte, created_at và chỉ số giờ = int64 BE, sig = 64 byte thô, str(x) = uint16 BE số byte ‖ UTF-8 đúng
  như chuỗi trên dây (không chuẩn hóa Unicode);
- PIN = UTF-8 của đúng 6 chữ số (giữ số 0 đầu); Argon2id phiên bản 0x13, không secret, không dữ liệu kèm.
"""
import struct
import uuid
from urllib.parse import quote

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import hmac as crypto_hmac
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from handlive_protocol_derivations import b64u, hkdf, test_bytes, uuid_bytes

OFFER_LABEL = b"HL1|offer|"
CONFIRM_LABEL = b"HL1|confirm|"
DONE_LABEL = b"HL1|done|"
PRK_CHECK_LABEL = {"client": b"HL1|prk-check-c|", "server": b"HL1|prk-check-s|"}
ATTESTATION_LABEL = b"HLPAIR1"
DISCOVERY_LABEL = b"HLDISC1"
PAIR_AUTH_INFO = "handlive/v1/pair-auth"
DISCOVERY_INFO = "handlive/v1/discovery"
HOUR_MS = 3_600_000
# 0.6.2: K_pin = Argon2id(PIN, salt = nonce_c ‖ nonce_s, t = 3, m = 64 MiB, p = 4, L = 32); phiên bản 0x13 (RFC 9106).
PIN_ARGON2 = {"variant": "argon2id", "version": 19, "t": 3, "m_kib": 65536, "p": 4, "length": 32}


def sha256(data: bytes) -> bytes:
    h = hashes.Hash(hashes.SHA256())
    h.update(data)
    return h.finalize()


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    h = crypto_hmac.HMAC(key, hashes.SHA256())
    h.update(msg)
    return h.finalize()


def argon2id(password: bytes, salt: bytes, params: dict) -> bytes:
    assert params["variant"] == "argon2id" and params["version"] == 19
    return Argon2id(salt=salt, length=params["length"], iterations=params["t"], lanes=params["p"],
                    memory_cost=params["m_kib"]).derive(password)


def pin_key(pin: str, nonce_c: bytes, nonce_s: bytes, params: dict = PIN_ARGON2) -> bytes:
    """K_pin: mật khẩu = UTF-8 của chuỗi PIN, salt = nonce_c ‖ nonce_s (64 byte)."""
    return argon2id(pin.encode(), nonce_c + nonce_s, params)


def pair_auth_key(secret: bytes, nonce_c: bytes, nonce_s: bytes) -> bytes:
    """K_pa = HKDF-SHA256(ikm = pairing_secret hoặc K_pin, salt = nonce_c ‖ nonce_s, info "handlive/v1/pair-auth")."""
    return hkdf(secret, PAIR_AUTH_INFO.encode(), 32, nonce_c + nonce_s)


def str_field(text: str, order: str = ">") -> bytes:
    """str(x) = uint16 độ dài (số byte UTF-8) ‖ UTF-8; order "<" chỉ để dựng vector âm."""
    raw = text.encode()
    return struct.pack(f"{order}H", len(raw)) + raw


def offer_parts(client: dict, server: dict, tls_sha256: bytes, label: bytes = OFFER_LABEL,
                str_order: str = ">") -> list[tuple[str, bytes]]:
    """T_offer (API 3). client/server: {device_id, nonce, ik_sig_pub, ik_dh_pub, name}."""
    parts = [("label", label)]
    for side, party in (("c", client), ("s", server)):
        parts += [(f"device_id_{side}", uuid_bytes(party["device_id"])), (f"nonce_{side}", party["nonce"]),
                  (f"ik_sig_pub_{side}", party["ik_sig_pub"]), (f"ik_dh_pub_{side}", party["ik_dh_pub"])]
        if side == "s":
            parts.append(("tls_sha256", tls_sha256))
        parts.append((f"name_{side}", str_field(party["name"], str_order)))
    return parts


def confirm_parts(t_offer: bytes, pair_id: str, created_at: int, sig: bytes, label: bytes = CONFIRM_LABEL,
                  int_order: str = ">") -> list[tuple[str, bytes]]:
    """Chuỗi MAC của pair/confirm (API 4): "HL1|confirm|" ‖ T_offer ‖ pair_id ‖ created_at ‖ sig."""
    return [("label", label), ("t_offer", t_offer), ("pair_id", uuid_bytes(pair_id)),
            ("created_at", struct.pack(f"{int_order}q", created_at)), ("sig", sig)]


def done_parts(pair_id: str, sig: bytes, label: bytes = DONE_LABEL) -> list[tuple[str, bytes]]:
    """Chuỗi MAC của pair/done (API 5): "HL1|done|" ‖ pair_id ‖ sig."""
    return [("label", label), ("pair_id", uuid_bytes(pair_id)), ("sig", sig)]


def prk_check_input(role: str, pair_id: str) -> bytes:
    return PRK_CHECK_LABEL[role] + uuid_bytes(pair_id)


def attestation_parts(pair_id: str, android_id: str, client_id: str, android_pub: bytes, client_pub: bytes,
                      created_at: int, int_order: str = ">") -> list[tuple[str, bytes]]:
    """0.6.2: "HLPAIR1" ‖ pair_id ‖ device_id Android ‖ device_id client ‖ ik_sig_pub Android ‖ ik_sig_pub client ‖
    created_at."""
    return [("label", ATTESTATION_LABEL), ("pair_id", uuid_bytes(pair_id)),
            ("device_id_android", uuid_bytes(android_id)), ("device_id_client", uuid_bytes(client_id)),
            ("ik_sig_pub_android", android_pub), ("ik_sig_pub_client", client_pub),
            ("created_at", struct.pack(f"{int_order}q", created_at))]


def joined(parts: list[tuple[str, bytes]]) -> bytes:
    return b"".join(b for _, b in parts)


def parts_json(parts: list[tuple[str, bytes]]) -> list[dict]:
    return [{"field": f, "hex": b.hex()} for f, b in parts]


def first_hex8(data: bytes) -> str:
    """8 chữ số hex thường đầu tiên (4 byte đầu)."""
    return data[:4].hex()


def security_code(attestation: bytes) -> str:
    """PAIR-02 trường 10: 8 chữ số hex thường đầu của SHA-256(attestation)."""
    return first_hex8(sha256(attestation))


def pairing_request_hint(pk: bytes) -> str:
    """TXT pr (0.4.1, PAIR-01 bước 6): 8 chữ số hex thường đầu của SHA-256 trên 32 byte đã giải của pk."""
    return first_hex8(sha256(pk))


def qr_uri(pk: bytes, ps: bytes, name: str, rv: bytes | None) -> str:
    """API 1, dạng chuẩn phía sinh: thứ tự v, pk, ps, d, rv; d mã hóa phần trăm UTF-8 mọi byte ngoài bộ
    unreserved của RFC 3986 (hex in hoa, dấu cách = %20)."""
    uri = f"handlive://pair?v=1&pk={b64u(pk)}&ps={b64u(ps)}&d={quote(name, safe='')}"
    return uri + (f"&rv={b64u(rv)}" if rv is not None else "")


def uuid7(ts_ms: int, label: str) -> str:
    """UUIDv7 tất định cho id envelope: 48 bit ts ‖ version 7 ‖ bit ngẫu nhiên = test_bytes(label)."""
    b = bytearray(ts_ms.to_bytes(6, "big") + test_bytes(f"uuid7 {label}", 10))
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(b)))


def discovery_key(prk: bytes) -> bytes:
    """K_disc = HKDF(PRK, salt rỗng, info "handlive/v1/discovery", L = 32)."""
    return hkdf(prk, DISCOVERY_INFO.encode(), 32)


def hour_index(now_ms: int) -> int:
    """floor(now_ms / 3 600 000) — phép chia làm tròn xuống, kể cả với số âm."""
    return now_ms // HOUR_MS


def discovery_message(hour: int, label: bytes = DISCOVERY_LABEL, int_format: str = ">q") -> bytes:
    """"HLDISC1" ‖ int64 BE của chỉ số giờ; label/int_format khác chỉ để dựng vector âm."""
    return label + struct.pack(int_format, hour)


def discovery_hint(key: bytes, hour: int, **mistake) -> str:
    return first_hex8(hmac_sha256(key, discovery_message(hour, **mistake)))
