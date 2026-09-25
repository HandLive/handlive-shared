"""Phần dùng chung của phía KIỂM pair-handshake.json — cài độc lập với phía sinh (pairing_discovery_derivations.py).

- Argon2id: argon2-cffi (bản C tham chiếu của PHC); phía sinh dùng Argon2id của OpenSSL qua `cryptography`.
- HKDF/HMAC/SHA-256: hashlib + hmac (verify_common); X25519/Ed25519: libsodium qua pynacl.
- T_offer, chuỗi MAC và attestation được dựng lại từ các TRƯỜNG JSON của thông điệp `pair`, không từ trường hex.
- Các hàm *_failure mô phỏng phép kiểm của bên nhận theo đúng thứ tự spec và trả phép kiểm ĐẦU TIÊN thất bại.
"""
import hmac
import json
import struct

from argon2.low_level import Type, hash_secret_raw

from verify_common import H, b64_decode_strict, b64u_decode, hkdf, hmac256, sha256, uuid16, x25519
from verify_session_checks import device_id
from verify_signature_checks import verifies

# 0.6.2: t = 3, m = 64 MiB, p = 4, L = 32; Argon2 phiên bản 0x13 = 19 (RFC 9106).
SPEC_ARGON2 = {"variant": "argon2id", "version": 19, "t": 3, "m_kib": 65536, "p": 4, "length": 32}
FIELDS = {
    "hello": ["mode", "device_id", "nonce", "name", "platform", "model", "ik_sig_pub", "ik_dh_pub"],
    "offer": ["device_id", "nonce", "name", "model", "os_version", "ik_sig_pub", "ik_dh_pub", "tls_sha256", "mac"],
    "confirm": ["pair_id", "created_at", "sig", "prk_check", "mac"],
    "done": ["sig", "prk_check", "mac"],
    "error": ["code", "message", "attempts_left"],
}
PAIR_AUTH_INFO = b"handlive/v1/pair-auth"
PRK_INFO = b"handlive/v1/pair"


def argon2id(pin: str, salt: bytes, params: dict) -> bytes:
    assert params["variant"] == "argon2id"
    return hash_secret_raw(pin.encode(), salt, time_cost=params["t"], memory_cost=params["m_kib"],
                           parallelism=params["p"], hash_len=params["length"], type=Type.ID,
                           version=params["version"])


def str_field(text: str, order: str = ">") -> bytes:
    raw = text.encode()
    return struct.pack(order + "H", len(raw)) + raw


def transcript_parts(hello: dict, offer: dict, str_order: str = ">") -> list[tuple[str, bytes]]:
    """T_offer (API 3) dựng từ `data` đã parse của pair/hello và pair/offer."""
    parts = [("label", b"HL1|offer|")]
    for side, d in (("c", hello), ("s", offer)):
        parts += [(f"device_id_{side}", uuid16(d["device_id"])), (f"nonce_{side}", b64u_decode(d["nonce"])),
                  (f"ik_sig_pub_{side}", b64u_decode(d["ik_sig_pub"])), (f"ik_dh_pub_{side}", b64u_decode(d["ik_dh_pub"]))]
        if side == "s":
            parts.append(("tls_sha256", b64u_decode(d["tls_sha256"])))
        parts.append((f"name_{side}", str_field(d["name"], str_order)))
    return parts


def attestation(pair_id: str, android_id: str, client_id: str, android_pub: bytes, client_pub: bytes,
                created_at: int, int_order: str = ">") -> bytes:
    return (b"HLPAIR1" + uuid16(pair_id) + uuid16(android_id) + uuid16(client_id) + android_pub + client_pub
            + struct.pack(int_order + "q", created_at))


def confirm_input(t_offer: bytes, pair_id: str, created_at: int, sig: bytes) -> bytes:
    return b"HL1|confirm|" + t_offer + uuid16(pair_id) + struct.pack(">q", created_at) + sig


def done_input(pair_id: str, sig: bytes) -> bytes:
    return b"HL1|done|" + uuid16(pair_id) + sig


def is_uuid7_at(u: str, ts: int) -> bool:
    b = uuid16(u)
    return b[6] >> 4 == 7 and b[8] >> 6 == 2 and int.from_bytes(b[:6], "big") == ts


def read_message(c, where: str, wire: str, plaintext: str, op: str) -> dict:
    """Envelope `type = pair` không mã hóa (0.5.1): payload = b64 của bản rõ; bản rõ gọn, đúng thứ tự trường."""
    env = json.loads(wire)
    c.eq(f"{where} envelope v/type", (env["v"], env["type"]), (1, "pair"))
    c.true(f"{where} id là UUIDv7 mang đúng ts", is_uuid7_at(env["id"], env["ts"]))
    c.eq(f"{where} payload b64 = bản rõ", b64_decode_strict(env["payload"]).decode(), plaintext)
    body = json.loads(plaintext)
    c.eq(f"{where} op", body["op"], op)
    c.eq(f"{where} thứ tự trường", list(body["data"]), FIELDS[op])
    c.eq(f"{where} JSON gọn", json.dumps(body, separators=(",", ":"), ensure_ascii=False), plaintext)
    return body["data"]


def macs_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


class Pairing:
    """Giá trị đúng của một vector dương, tính lại từ khóa bí mật và JSON của bốn thông điệp."""

    def __init__(self, v: dict):
        self.v, self.qr, self.name = v, v["mode"] == "qr", v["name"]
        self.hello = json.loads(v["hello_plaintext"])["data"]
        self.offer = json.loads(v["offer_plaintext"])["data"]
        self.confirm = json.loads(v["confirm_plaintext"])["data"]
        self.done = json.loads(v["done_plaintext"])["data"]
        self.pair_id, self.created_at = self.confirm["pair_id"], self.confirm["created_at"]
        self.client_id, self.android_id = self.hello["device_id"], self.offer["device_id"]
        self.client_pub, self.android_pub = b64u_decode(self.hello["ik_sig_pub"]), b64u_decode(self.offer["ik_sig_pub"])
        self.nonce_c, self.nonce_s = b64u_decode(self.hello["nonce"]), b64u_decode(self.offer["nonce"])
        self.salt = self.nonce_c + self.nonce_s
        self.tls = H(v["tls_sha256"])  # chứng chỉ của kết nối hiện tại mà client thấy (LAN)
        self.pk = b64u_decode(v["qr_pk"]) if self.qr else None
        self.secret = H(v["pairing_secret"]) if self.qr else argon2id(v["pin"], self.salt, SPEC_ARGON2)
        self.k_pa = hkdf(self.secret, PAIR_AUTH_INFO, 32, self.salt)
        self.t_offer_parts = transcript_parts(self.hello, self.offer)
        self.t_offer = b"".join(b for _, b in self.t_offer_parts)
        self.attestation = attestation(self.pair_id, self.android_id, self.client_id, self.android_pub,
                                       self.client_pub, self.created_at)
        self.dh = x25519(H(v["client_ik_dh_priv"]), b64u_decode(self.offer["ik_dh_pub"]))
        self.dh_android = x25519(H(v["android_ik_dh_priv"]), b64u_decode(self.hello["ik_dh_pub"]))
        self.prk_salt_input = b"".join(sorted([uuid16(self.client_id), uuid16(self.android_id)]))
        self.prk = hkdf(self.dh + self.secret, PRK_INFO, 32, sha256(self.prk_salt_input))

    def prk_check(self, role: str, pair_id: str | None = None) -> bytes:
        return hmac256(self.prk, f"HL1|prk-check-{role}|".encode() + uuid16(pair_id or self.pair_id))

    # Phép kiểm của bên nhận, theo thứ tự spec; trả phép kiểm đầu tiên thất bại hoặc None.
    def hello_failure(self, d: dict) -> str | None:
        """Android, API 2 quy tắc 2 rồi 3."""
        if self.qr and b64u_decode(d["ik_dh_pub"]) != self.pk:
            return "hello_key"
        if device_id(b64u_decode(d["ik_sig_pub"])) != d["device_id"]:
            return "hello_device_id"
        return None

    def offer_failure(self, d: dict) -> str | None:
        """Client, API 3 quy tắc 3: mac → device_id của ik_sig_pub → (LAN) tls_sha256 = chứng chỉ của kết nối."""
        t_offer = b"".join(b for _, b in transcript_parts(self.hello, d))
        if not macs_equal(hmac256(self.k_pa, t_offer), b64u_decode(d["mac"])):
            return "offer_mac"
        if device_id(b64u_decode(d["ik_sig_pub"])) != d["device_id"]:
            return "offer_device_id"
        if b64u_decode(d["tls_sha256"]) != self.tls:
            return "offer_tls"
        return None

    def confirm_failure(self, d: dict) -> str | None:
        """Android, API 4 quy tắc 1–2: mac → prk_check → chữ ký client trên attestation dựng lại."""
        sig = b64u_decode(d["sig"])
        if not macs_equal(hmac256(self.k_pa, confirm_input(self.t_offer, d["pair_id"], d["created_at"], sig)),
                          b64u_decode(d["mac"])):
            return "confirm_mac"
        if not macs_equal(self.prk_check("c", d["pair_id"]), b64u_decode(d["prk_check"])):
            return "prk_check_c"
        att = attestation(d["pair_id"], self.android_id, self.client_id, self.android_pub, self.client_pub,
                          d["created_at"])
        return None if verifies(self.client_pub, att, sig) else "sig_c"

    def done_failure(self, d: dict) -> str | None:
        """Client, API 5 quy tắc 1: mac → prk_check → chữ ký Android trên attestation."""
        sig = b64u_decode(d["sig"])
        if not macs_equal(hmac256(self.k_pa, done_input(self.pair_id, sig)), b64u_decode(d["mac"])):
            return "done_mac"
        if not macs_equal(self.prk_check("s"), b64u_decode(d["prk_check"])):
            return "prk_check_s"
        return None if verifies(self.android_pub, self.attestation, sig) else "sig_s"
