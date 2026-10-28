"""Noise_NNpsk0_25519_ChaChaPoly_SHA256 (Noise Protocol Framework rev. 34), chỉ message 1 (token "psk, e") —
"khung đầu" (first frame) của một liên kết ghép đôi qua Bluetooth (00-common-specs.md 0.4.5 "Link-security
handshake" bước 2–3, "Pairing mode"). HASHLEN = 32 (SHA-256) nên temp_k/temp_k1/temp_k2 không bị cắt (quy tắc cắt
chỉ áp dụng khi HASHLEN = 64).

Không phải vector công bố của tài liệu Noise — draft/tài liệu Noise không phát hành vector cho psk/prologue riêng
của HandLive. Đây là cách HandLive dùng đúng thuật toán của tài liệu đó (InitializeSymmetric, MixHash,
MixKeyAndHash, EncryptAndHash) cho bộ psk/prologue của mình, nên cần một vòng rà soát riêng (không tự xác nhận được
bằng vector bên ngoài) trước khi A7.1a/M7.1b khoá theo.
"""
import hashlib
import hmac as _hmac

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from handlive_protocol_derivations import x25519_pub

PROTOCOL_NAME = b"Noise_NNpsk0_25519_ChaChaPoly_SHA256"


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return _hmac.new(key, msg, hashlib.sha256).digest()


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def initialize_symmetric(protocol_name: bytes = PROTOCOL_NAME) -> tuple[bytes, bytes]:
    """h = ck = protocol_name nếu ≤ 32 byte, ngược lại SHA-256(protocol_name) (ở đây 37 byte > 32). Trả (h, ck)."""
    h = protocol_name if len(protocol_name) <= 32 else _sha256(protocol_name)
    return h, h


def mix_key_and_hash(ck: bytes, h: bytes, ikm: bytes) -> dict:
    """Token "psk": HKDF nội bộ của Noise (3 ngõ ra qua HMAC) rồi MixHash(temp_h); InitializeKey(temp_k)."""
    temp_key = _hmac_sha256(ck, ikm)
    out1 = _hmac_sha256(temp_key, b"\x01")
    out2 = _hmac_sha256(temp_key, out1 + b"\x02")
    out3 = _hmac_sha256(temp_key, out2 + b"\x03")
    return {"temp_key": temp_key, "ck": out1, "temp_h": out2, "temp_k": out3, "h": _sha256(h + out2)}


def first_message(psk: bytes, prologue: bytes, e_priv: bytes) -> dict:
    """Dựng message 1 ("psk, e") của C→S. `message1` = e.pub (32) ‖ EncryptAndHash("") (16, chỉ có tag vì
    plaintext rỗng)."""
    h0, ck0 = initialize_symmetric()
    h1 = _sha256(h0 + prologue)  # MixHash(prologue)
    psk_step = mix_key_and_hash(ck0, h1, psk)
    h2, ck1, k = psk_step["h"], psk_step["ck"], psk_step["temp_k"]
    e_pub = x25519_pub(e_priv)
    h3 = _sha256(h2 + e_pub)  # MixHash(e.pub); khóa công khai tạm thời không bao giờ được mã hóa
    nonce = bytes(4) + (0).to_bytes(8, "little")  # n = 0 (lần ENCRYPT đầu tiên của hướng này)
    ciphertext = ChaCha20Poly1305(k).encrypt(nonce, b"", h3)  # EncryptAndHash(""), ad = h3
    h4 = _sha256(h3 + ciphertext)  # MixHash(ciphertext)
    return {"protocol_name": PROTOCOL_NAME, "h0": h0, "prologue": prologue, "h1": h1, "psk": psk,
            "mix_key_and_hash": psk_step, "h2": h2, "ck1": ck1, "k": k, "e_priv": e_priv, "e_pub": e_pub,
            "h3": h3, "nonce": nonce, "ciphertext_tag": ciphertext, "h4": h4, "message1": e_pub + ciphertext}


def try_open_first_message(psk: bytes, prologue: bytes, e_pub: bytes, ciphertext_tag: bytes) -> bytes | None:
    """Phía S: thử một psk ứng viên. Trả b"" nếu tag khớp (xác thực được "khung đầu"), None nếu không — như
    `reject`, không lộ lý do."""
    h0, ck0 = initialize_symmetric()
    h1 = _sha256(h0 + prologue)
    psk_step = mix_key_and_hash(ck0, h1, psk)
    h2, k = psk_step["h"], psk_step["temp_k"]
    h3 = _sha256(h2 + e_pub)
    nonce = bytes(4) + (0).to_bytes(8, "little")
    try:
        return ChaCha20Poly1305(k).decrypt(nonce, ciphertext_tag, h3)
    except Exception:
        return None
