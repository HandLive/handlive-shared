"""Kiểm bt-pairing.json bằng thư viện độc lập: HKDF/HMAC qua verify_common (hashlib/hmac), X25519 qua
`x25519_base` (pynacl), ChaCha20Poly1305 kiểm chéo `cryptography` + libsodium ietf — độc lập với
noise_nnpsk0.py (phía sinh).
"""
import hashlib
import hmac

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from nacl.bindings import crypto_aead_chacha20poly1305_ietf_decrypt
from nacl.exceptions import CryptoError

from verify_common import H, hkdf, hmac256, x25519_base

PDISC_INFO = b"handlive/v1/bt-pair-disc"
PLINK_INFO = b"handlive/v1/bt-pair-link"
PR_BT_LABEL = b"HLBTPAIR1"
PROTOCOL_NAME = b"Noise_NNpsk0_25519_ChaChaPoly_SHA256"
PROLOGUE_LABEL = b"HLBT1"
REASONS = {"wrong_key", "tag_mismatch", "message_tampered", "aad_mismatch"}
ZERO_NONCE = bytes(12)


def _sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _ck_h_k_after_psk(prologue: bytes, psk: bytes) -> tuple[bytes, bytes]:
    """InitializeSymmetric → MixHash(prologue) → token "psk" (MixKeyAndHash). Trả (h, k) sau bước này."""
    h0 = _sha256(PROTOCOL_NAME)  # 37 byte > HASHLEN 32
    h1 = _sha256(h0 + prologue)
    temp_key = _hmac(h0, psk)
    out1 = _hmac(temp_key, b"\x01")
    out2 = _hmac(temp_key, out1 + b"\x02")
    out3 = _hmac(temp_key, out2 + b"\x03")
    return _sha256(h1 + out2), out3


def _open(psk: bytes, prologue: bytes, e_pub: bytes, ciphertext_tag: bytes):
    """Trả (mở bằng cryptography, mở bằng libsodium, h sau token "e") — None khi tag không khớp."""
    h, k = _ck_h_k_after_psk(prologue, psk)
    h3 = _sha256(h + e_pub)
    try:
        a = ChaCha20Poly1305(k).decrypt(ZERO_NONCE, ciphertext_tag, h3)
    except InvalidTag:
        a = None
    try:
        b = crypto_aead_chacha20poly1305_ietf_decrypt(ciphertext_tag, h3, ZERO_NONCE, k)
    except CryptoError:
        b = None
    return a, b, h3


def _check_key(c, n: str, v: dict, pair_prk: dict) -> bytes:
    pv = pair_prk[v["name"]]
    c.eq(f"{n} pairing_secret lấy từ pair-prk.json", (v["pairing_secret_source"], v["pairing_secret"]),
         ("pair-prk.json", pv["pairing_secret"]))
    secret = H(v["pairing_secret"])
    pdisc = hkdf(secret, PDISC_INFO, 32)
    plink = hkdf(secret, PLINK_INFO, 32)
    c.eq(f"{n} K_bt_pdisc", v["k_bt_pdisc"], pdisc.hex())
    c.eq(f"{n} K_bt_plink", v["k_bt_plink"], plink.hex())
    mac = hmac256(pdisc, PR_BT_LABEL)
    c.eq(f"{n} pr_bt_mac", v["pr_bt_mac"], mac.hex())
    c.eq(f"{n} pr_bt = 4 byte đầu của pr_bt_mac", v["pr_bt"], mac[:4].hex())
    return plink


def _check_first_frame(c, n: str, v: dict) -> None:
    psk, prologue = H(v["psk"]), H(v["prologue"])
    c.eq(f"{n} prologue = nhãn ‖ n_s", prologue, PROLOGUE_LABEL + H(v["n_s"]))
    c.eq(f"{n} e_pub = X25519 base point của e_priv", v["e_pub"], x25519_base(H(v["e_priv"])).hex())
    a, b, h3 = _open(psk, prologue, H(v["e_pub"]), H(v["ciphertext_tag"]))
    c.eq(f"{n} h_after_e", h3.hex(), v["h_after_e"])
    c.eq(f"{n} mở được bằng cryptography (đúng psk)", a, b"")
    c.eq(f"{n} mở được bằng libsodium (đúng psk)", b, b"")
    c.eq(f"{n} message1 = e_pub ‖ ciphertext_tag", v["message1"], v["e_pub"] + v["ciphertext_tag"])
    rlen = 1 + len(H(v["message1"]))
    c.eq(f"{n} rlen = 1 (kind) + độ dài message1", v["rlen"], rlen)
    c.eq(f"{n} record = rlen(2 BE) ‖ kind(0x02) ‖ message1", H(v["record"]),
         rlen.to_bytes(2, "big") + bytes([0x02]) + H(v["message1"]))


def _check_negative(c, n: str, v: dict, plink: dict) -> None:
    reason = v["reason"]
    c.true(f"{n} reason nằm trong tập đã định", reason in REASONS)
    prologue = PROLOGUE_LABEL + H(v["n_s"])
    psk = H(v["wrong_psk"]) if reason == "wrong_key" else plink["cặp 1"]
    a, b, _ = _open(psk, prologue, H(v["e_pub"]), H(v["ciphertext_tag"]))
    c.eq(f"{n} phải bị từ chối (cả hai đường)", (a, b), (None, None))


def check_bt_pairing(c, doc: dict, all_docs: dict) -> None:
    pair_prk = {v["name"]: v for v in all_docs["pair-prk.json"]["vectors"]}
    plink, kinds = {}, set()
    for v in doc["vectors"]:
        n = f"bt-pairing/{v['name']}"
        kinds.add(v["kind"])
        if v["kind"] == "key":
            plink[v["name"]] = _check_key(c, n, v, pair_prk)
        elif v["kind"] == "first_frame":
            _check_first_frame(c, n, v)
        else:
            c.true(f"{n} kind {v['kind']!r} không nằm trong tập đã định", False)
    c.eq("bt-pairing: có cả hai kind", kinds, {"key", "first_frame"})
    c.eq("bt-pairing: mỗi cặp của pair-prk.json có một vector key", sorted(plink), sorted(pair_prk))
    for v in doc["invalid_vectors"]:
        _check_negative(c, f"bt-pairing/{v['name']}", v, plink)
    c.eq("bt-pairing: đủ loại vector âm", {v["reason"] for v in doc["invalid_vectors"]}, REASONS)


CHECKS = {"bt-pairing.json": check_bt_pairing}
