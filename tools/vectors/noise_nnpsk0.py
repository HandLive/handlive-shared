"""Noise_NNpsk0_25519_ChaChaPoly_SHA256 (Noise Protocol Framework rev. 34): message 1 ("psk, e") và message 2
("e, ee") đủ cho cả "khung đầu" ghép đôi (00-common-specs.md 0.4.5 "Link-security handshake" bước 2–3, "Pairing
mode") và bắt tay bảo mật liên kết đầy đủ (bước 1–5, psk = `K_bt_link`, dùng cho các cặp đã ghép). HASHLEN = 32
(SHA-256) nên temp_k/temp_k1/temp_k2 không bị cắt (quy tắc cắt chỉ áp dụng khi HASHLEN = 64).

Rev. 34 §9.2 (chế độ psk): mỗi token "e" làm MixHash(e.pub) RỒI MixKey(e.pub) — không chỉ MixHash như pattern
không-psk. Thiếu bước MixKey(e.pub) này (lỗi #3418, bắt được qua kiểm chéo bằng thư viện `noiseprotocol` thật)
làm ck lan sai sang bước kế tiếp: message 1 mã nhầm bằng k của token "psk" thay vì k của token "e"; message 2
tính "ee" trên ck sai nên ck2/Split() cũng sai theo, dù `e`/`e.pub` trên dây vẫn đúng (không đổi).

Không phải vector công bố của tài liệu Noise — draft/tài liệu Noise không phát hành vector cho psk/prologue riêng
của HandLive. Đây là cách HandLive dùng đúng thuật toán của tài liệu đó (InitializeSymmetric, MixHash,
MixKeyAndHash, MixKey, EncryptAndHash, Split) cho bộ psk/prologue của mình, nên cần một vòng rà soát riêng (không
tự xác nhận được bằng vector bên ngoài) trước khi A7.1a/M7.1b khoá theo.
"""
import hashlib
import hmac as _hmac

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from handlive_protocol_derivations import x25519_dh as _x25519_dh
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
    """Dựng message 1 ("psk, e") của C→S. Noise rev. 34 §9.2 (chế độ psk): mỗi token "e" làm MixHash(e.pub) RỒI
    MixKey(e.pub) — khác pattern không-psk, nơi "e" chỉ MixHash. `k` dùng để mã hoá payload vì vậy là k SAU
    MixKey(e.pub) của token "e", không phải k của token "psk" (bị đè ngay). `message1` = e.pub (32) ‖
    EncryptAndHash("") (16, chỉ có tag vì plaintext rỗng)."""
    h0, ck0 = initialize_symmetric()
    h1 = _sha256(h0 + prologue)  # MixHash(prologue)
    psk_step = mix_key_and_hash(ck0, h1, psk)  # token "psk": MixKeyAndHash
    h2, ck_psk = psk_step["h"], psk_step["ck"]
    e_pub = x25519_pub(e_priv)
    h3 = _sha256(h2 + e_pub)  # MixHash(e.pub); khóa công khai tạm thời không bao giờ được mã hóa
    e_step = mix_key(ck_psk, e_pub)  # token "e", phần thêm của chế độ psk: MixKey(e.pub)
    ck1, k = e_step["ck"], e_step["temp_k"]
    nonce = bytes(4) + (0).to_bytes(8, "little")  # n = 0 (lần ENCRYPT đầu tiên của hướng này)
    ciphertext = ChaCha20Poly1305(k).encrypt(nonce, b"", h3)  # EncryptAndHash(""), ad = h3 (MixKey không đụng h)
    h4 = _sha256(h3 + ciphertext)  # MixHash(ciphertext)
    return {"protocol_name": PROTOCOL_NAME, "h0": h0, "prologue": prologue, "h1": h1, "psk": psk,
            "mix_key_and_hash": psk_step, "h2": h2, "ck_after_psk": ck_psk, "mix_key_e": e_step, "ck1": ck1, "k": k,
            "e_priv": e_priv, "e_pub": e_pub, "h3": h3, "nonce": nonce, "ciphertext_tag": ciphertext, "h4": h4,
            "message1": e_pub + ciphertext}


def try_open_first_message(psk: bytes, prologue: bytes, e_pub: bytes, ciphertext_tag: bytes) -> bytes | None:
    """Phía S: thử một psk ứng viên. Trả b"" nếu tag khớp (xác thực được "khung đầu"), None nếu không — như
    `reject`, không lộ lý do."""
    h0, ck0 = initialize_symmetric()
    h1 = _sha256(h0 + prologue)
    psk_step = mix_key_and_hash(ck0, h1, psk)
    h2, ck_psk = psk_step["h"], psk_step["ck"]
    h3 = _sha256(h2 + e_pub)
    e_step = mix_key(ck_psk, e_pub)
    k = e_step["temp_k"]
    nonce = bytes(4) + (0).to_bytes(8, "little")
    try:
        return ChaCha20Poly1305(k).decrypt(nonce, ciphertext_tag, h3)
    except Exception:
        return None


def mix_key(ck: bytes, ikm: bytes) -> dict:
    """Token "ee"/"es"/"se"/"ss": MixKey (2 ngõ ra qua HMAC, KHÔNG MixHash — khác token "psk")."""
    temp_key = _hmac_sha256(ck, ikm)
    out1 = _hmac_sha256(temp_key, b"\x01")
    out2 = _hmac_sha256(temp_key, out1 + b"\x02")
    return {"temp_key": temp_key, "ck": out1, "temp_k": out2}


def second_message(ck1: bytes, h_after_message1: bytes, e_priv_s: bytes, e_pub_c: bytes) -> dict:
    """Dựng message 2 ("e, ee") của S→C, tiếp theo sau `first_message`. `ck1`/`h_after_message1` = `ck1`/`h4` của
    `first_message`. Như message 1, token "e" ở chế độ psk làm MixHash RỒI MixKey(e.pub) trước khi token "ee" làm
    MixKey(DH) — `k` dùng để mã hoá payload là k SAU "ee", vì "ee" đến sau và đè k của "e". `message2` = e.pub
    của S (32) ‖ EncryptAndHash("") (16)."""
    e_pub_s = x25519_pub(e_priv_s)
    h5 = _sha256(h_after_message1 + e_pub_s)  # MixHash(e.pub) của token "e"
    e_step = mix_key(ck1, e_pub_s)  # token "e", phần thêm của chế độ psk: MixKey(e.pub)
    dh = _x25519_dh(e_priv_s, e_pub_c)
    ee_step = mix_key(e_step["ck"], dh)  # token "ee": MixKey(DH(e,re))
    ck2, k = ee_step["ck"], ee_step["temp_k"]
    nonce = bytes(4) + (0).to_bytes(8, "little")  # n = 0, k vừa được InitializeKey lại
    ciphertext = ChaCha20Poly1305(k).encrypt(nonce, b"", h5)  # ad = h5 (MixKey không đụng h)
    h6 = _sha256(h5 + ciphertext)
    return {"h5": h5, "mix_key_e": e_step, "dh": dh, "mix_key_ee": ee_step, "ck2": ck2, "k": k, "e_priv": e_priv_s,
            "e_pub": e_pub_s, "nonce": nonce, "ciphertext_tag": ciphertext, "h6": h6, "message2": e_pub_s + ciphertext}


def try_open_second_message(ck1: bytes, h_after_message1: bytes, e_priv_c: bytes, e_pub_s: bytes,
                             ciphertext_tag: bytes) -> tuple[bytes | None, bytes | None, bytes | None]:
    """Phía C: mở message 2. Trả (plaintext hoặc None, ck2, h6) — `ck2`/`h6` cần cho `split()` dù `plaintext` là
    None (để caller tự quyết có đóng kênh hay không, không lộ gì qua số lượng giá trị trả về)."""
    h5 = _sha256(h_after_message1 + e_pub_s)
    e_step = mix_key(ck1, e_pub_s)
    dh = _x25519_dh(e_priv_c, e_pub_s)
    ee_step = mix_key(e_step["ck"], dh)
    ck2, k = ee_step["ck"], ee_step["temp_k"]
    nonce = bytes(4) + (0).to_bytes(8, "little")
    h6 = _sha256(h5 + ciphertext_tag)
    try:
        pt = ChaCha20Poly1305(k).decrypt(nonce, ciphertext_tag, h5)
    except Exception:
        pt = None
    return pt, ck2, h6


def split(ck2: bytes) -> dict:
    """Split(): 2 CipherState, một cho mỗi hướng. `c1` dùng để C mã hoá/S giải mã; `c2` ngược lại (Noise rev. 34
    §5, "Split")."""
    temp_key = _hmac_sha256(ck2, b"")
    out1 = _hmac_sha256(temp_key, b"\x01")
    out2 = _hmac_sha256(temp_key, out1 + b"\x02")
    return {"temp_key": temp_key, "c1": out1, "c2": out2}
