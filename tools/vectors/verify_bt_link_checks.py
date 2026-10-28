"""Kiểm bt-link.json bằng thư viện độc lập với phía sinh: HKDF/HMAC qua verify_common (hashlib/hmac), X25519 qua
`x25519`/`x25519_base` (pynacl), ChaCha20Poly1305 kiểm chéo `cryptography` + libsodium ietf — độc lập với
noise_nnpsk0.py, giống verify_bt_pairing_checks.py nhưng thêm message 2 ("e, ee") và Split().
"""
import hashlib
import hmac

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from nacl.bindings import crypto_aead_chacha20poly1305_ietf_decrypt
from nacl.exceptions import CryptoError

from verify_common import H, hkdf, hmac256, x25519, x25519_base

DISC_INFO = b"handlive/v1/bt-discovery"
LINK_INFO = b"handlive/v1/bt-link"
HINT_LABEL = b"HLBTDISC1"
PROTOCOL_NAME = b"Noise_NNpsk0_25519_ChaChaPoly_SHA256"
PROLOGUE_LABEL = b"HLBT1"
REASONS = {"wrong_key", "tag_mismatch_noise1", "tag_mismatch_noise2", "replayed_channel"}
ZERO_NONCE = bytes(12)


def _sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _mix_key_and_hash(h: bytes, ck: bytes, ikm: bytes) -> tuple[bytes, bytes, bytes]:
    """Token "psk": 3 ngõ ra qua HMAC (khác token "ee", chỉ 2 ngõ ra) — trả (h mới, ck mới, k mới)."""
    temp_key = _hmac(ck, ikm)
    out1 = _hmac(temp_key, b"\x01")
    out2 = _hmac(temp_key, out1 + b"\x02")
    out3 = _hmac(temp_key, out2 + b"\x03")
    return _sha256(h + out2), out1, out3


def _mix_key(ck: bytes, ikm: bytes) -> tuple[bytes, bytes]:
    """Token "ee": trả (ck mới, k mới), KHÔNG đụng h."""
    temp_key = _hmac(ck, ikm)
    out1 = _hmac(temp_key, b"\x01")
    out2 = _hmac(temp_key, out1 + b"\x02")
    return out1, out2


def _open_chacha(k: bytes, aad: bytes, ciphertext_tag: bytes):
    """Trả (mở bằng cryptography, mở bằng libsodium) — None khi tag không khớp."""
    try:
        a = ChaCha20Poly1305(k).decrypt(ZERO_NONCE, ciphertext_tag, aad)
    except InvalidTag:
        a = None
    try:
        b = crypto_aead_chacha20poly1305_ietf_decrypt(ciphertext_tag, aad, ZERO_NONCE, k)
    except CryptoError:
        b = None
    return a, b


def _open_message1(psk: bytes, prologue: bytes, e_pub_c: bytes, ciphertext_tag: bytes):
    """Trả (mở cryptography, mở libsodium, h sau token "e" của C, ck sau token "psk")."""
    h0 = _sha256(PROTOCOL_NAME)
    h1 = _sha256(h0 + prologue)
    h2, ck1, k1 = _mix_key_and_hash(h1, h0, psk)
    h3 = _sha256(h2 + e_pub_c)
    a, b = _open_chacha(k1, h3, ciphertext_tag)
    return a, b, h3, ck1


def _open_message2(ck1: bytes, h_after_m1: bytes, e_priv_c: bytes, e_pub_s: bytes, ciphertext_tag: bytes):
    """Trả (mở cryptography, mở libsodium, h sau token "e" của S, ck sau token "ee")."""
    h5 = _sha256(h_after_m1 + e_pub_s)
    dh = x25519(e_priv_c, e_pub_s)
    ck2, k2 = _mix_key(ck1, dh)
    a, b = _open_chacha(k2, h5, ciphertext_tag)
    return a, b, h5, ck2


def _split(ck2: bytes) -> tuple[bytes, bytes]:
    temp_key = _hmac(ck2, b"")
    out1 = _hmac(temp_key, b"\x01")
    out2 = _hmac(temp_key, out1 + b"\x02")
    return out1, out2


def _check_key(c, n: str, v: dict, pair_prk: dict) -> bytes:
    pv = pair_prk[v["name"]]
    c.eq(f"{n} PRK lấy từ pair-prk.json", (v["prk_source"], v["prk"]), ("pair-prk.json", pv["prk"]))
    prk = H(v["prk"])
    disc, link = hkdf(prk, DISC_INFO, 32), hkdf(prk, LINK_INFO, 32)
    c.eq(f"{n} K_bt_disc", v["k_bt_disc"], disc.hex())
    c.eq(f"{n} K_bt_link", v["k_bt_link"], link.hex())
    return link


def _check_hint(c, n: str, v: dict, disc: dict) -> None:
    disc_key = disc[v["k_bt_disc_source"]]
    for e in v["epochs"]:
        msg = HINT_LABEL + e["epoch"].to_bytes(8, "big", signed=True)
        c.eq(f"{n} hint epoch {e['epoch']}", e["hint"], hmac256(disc_key, msg)[:4].hex())


def _check_handshake(c, n: str, v: dict) -> None:
    psk, prologue = H(v["psk"]), H(v["prologue"])
    c.eq(f"{n} prologue = nhãn ‖ n_s", prologue, PROLOGUE_LABEL + H(v["n_s"]))
    challenge_body = bytes([0x01]) + H(v["n_s"])
    c.eq(f"{n} challenge_record = rlen(2BE) ‖ kind(0x01) ‖ n_s", H(v["challenge_record"]),
         len(challenge_body).to_bytes(2, "big") + challenge_body)
    c.eq(f"{n} e_pub_c = X25519 base point của e_priv_c", v["e_pub_c"], x25519_base(H(v["e_priv_c"])).hex())

    a1, b1, h3, ck1 = _open_message1(psk, prologue, H(v["e_pub_c"]), H(v["ciphertext_tag_1"]))
    c.eq(f"{n} h_after_e_c", h3.hex(), v["h_after_e_c"])
    c.eq(f"{n} mở được noise1 (cryptography)", a1, b"")
    c.eq(f"{n} mở được noise1 (libsodium)", b1, b"")
    c.eq(f"{n} message1 = e_pub_c ‖ ciphertext_tag_1", v["message1"], v["e_pub_c"] + v["ciphertext_tag_1"])
    noise1_body = bytes([0x02]) + H(v["message1"])
    c.eq(f"{n} noise1_record = rlen(2BE) ‖ kind(0x02) ‖ message1", H(v["noise1_record"]),
         len(noise1_body).to_bytes(2, "big") + noise1_body)

    c.eq(f"{n} e_pub_s = X25519 base point của e_priv_s", v["e_pub_s"], x25519_base(H(v["e_priv_s"])).hex())
    a2, b2, h5, ck2 = _open_message2(ck1, H(v["h_after_message1"]), H(v["e_priv_c"]), H(v["e_pub_s"]),
                                      H(v["ciphertext_tag_2"]))
    c.eq(f"{n} h_after_e_s", h5.hex(), v["h_after_e_s"])
    c.eq(f"{n} mở được noise2 (cryptography)", a2, b"")
    c.eq(f"{n} mở được noise2 (libsodium)", b2, b"")
    c.eq(f"{n} ck_after_ee", ck2.hex(), v["ck_after_ee"])
    c.eq(f"{n} message2 = e_pub_s ‖ ciphertext_tag_2", v["message2"], v["e_pub_s"] + v["ciphertext_tag_2"])
    noise2_body = bytes([0x03]) + H(v["message2"])
    c.eq(f"{n} noise2_record = rlen(2BE) ‖ kind(0x03) ‖ message2", H(v["noise2_record"]),
         len(noise2_body).to_bytes(2, "big") + noise2_body)

    c1, c2 = _split(ck2)
    c.eq(f"{n} Split() c1", v["c1"], c1.hex())
    c.eq(f"{n} Split() c2", v["c2"], c2.hex())
    c.true(f"{n} c1 != c2", c1 != c2)


def _check_negative(c, n: str, v: dict, hs: dict, link: dict) -> None:
    reason = v["reason"]
    c.true(f"{n} reason nằm trong tập đã định", reason in REASONS)
    if reason == "tag_mismatch_noise2":
        ck1 = H(hs["ck_after_psk"])
        a, b, _, _ = _open_message2(ck1, H(hs["h_after_message1"]), H(hs["e_priv_c"]), H(v["e_pub_s"]),
                                     H(v["ciphertext_tag_2"]))
        c.eq(f"{n} phải bị từ chối (cả hai đường)", (a, b), (None, None))
        return
    prologue = PROLOGUE_LABEL + H(v["n_s"])
    psk = H(v["wrong_psk"]) if reason == "wrong_key" else link["cặp 1"]
    a, b, _, _ = _open_message1(psk, prologue, H(v["e_pub_c"]), H(v["ciphertext_tag_1"]))
    c.eq(f"{n} phải bị từ chối (cả hai đường)", (a, b), (None, None))


def check_bt_link(c, doc: dict, all_docs: dict) -> None:
    pair_prk = {v["name"]: v for v in all_docs["pair-prk.json"]["vectors"]}
    disc, link, kinds = {}, {}, set()
    handshake = None
    for v in doc["vectors"]:
        n = f"bt-link/{v['name']}"
        kinds.add(v["kind"])
        if v["kind"] == "key":
            disc[v["name"]] = H(v["k_bt_disc"])
            link[v["name"]] = _check_key(c, n, v, pair_prk)
        elif v["kind"] == "hint":
            _check_hint(c, n, v, disc)
        elif v["kind"] == "handshake":
            _check_handshake(c, n, v)
            handshake = v
        else:
            c.true(f"{n} kind {v['kind']!r} không nằm trong tập đã định", False)
    c.eq("bt-link: có đủ loại vector", kinds, {"key", "hint", "handshake"})
    for v in doc["invalid_vectors"]:
        _check_negative(c, f"bt-link/{v['name']}", v, handshake, link)
    c.eq("bt-link: đủ loại vector âm", {v["reason"] for v in doc["invalid_vectors"]}, REASONS)


CHECKS = {"bt-link.json": check_bt_link}
