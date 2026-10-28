"""Kiểm bt-frame.json bằng thư viện độc lập: ChaCha20-Poly1305 chéo `cryptography` + libsodium ietf (độc lập với
bt_frame_codec.py, vốn chỉ đóng gói byte không mã hoá); mọi luật cận (rlen, chan, more/long, BT_BULK_FRAGMENT_MAX,
BT_MESSAGE_MAX, BT_PREAUTH_RECORD_MAX) kiểm lại bằng số học thuần, không gọi lại bt_frame_codec.py.
"""
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from nacl.bindings import crypto_aead_chacha20poly1305_ietf_decrypt
from nacl.exceptions import CryptoError

from verify_common import H

RECORD_SIZES = {272, 1040, 4112}
CHAN_VALID = {0x01, 0x02}
BT_BULK_FRAGMENT_MAX = 1020
BT_MESSAGE_MAX = 256 * 1024
BT_PREAUTH_RECORD_MAX = 64
REASONS = {"rlen_out_of_bounds", "preauth_record_over_bound", "unknown_chan", "more_without_long",
           "bulk_fragment_over_max", "message_over_max"}


def _decrypt_both(key: bytes, nonce: bytes, ciphertext_tag: bytes):
    try:
        a = ChaCha20Poly1305(key).decrypt(nonce, ciphertext_tag, b"")
    except InvalidTag:
        a = None
    try:
        b = crypto_aead_chacha20poly1305_ietf_decrypt(ciphertext_tag, b"", nonce, key)
    except CryptoError:
        b = None
    return a, b


def _parse_plaintext(plaintext: bytes) -> dict:
    chan, flags = plaintext[0], plaintext[1]
    dlen = int.from_bytes(plaintext[2:4], "big")
    return {"chan": chan, "more": bool(flags & 0x01), "long": bool(flags & 0x02), "dlen": dlen,
            "data": plaintext[4:4 + dlen], "padding": plaintext[4 + dlen:]}


def _check_transport_frame(c, n: str, v: dict, c1: bytes) -> None:
    nonce = bytes(4) + v["counter"].to_bytes(8, "little")
    c.eq(f"{n} nonce = 4 byte 0 ‖ counter LE", v["nonce"], nonce.hex())
    a, b = _decrypt_both(c1, nonce, H(v["ciphertext_tag"]))
    c.eq(f"{n} giải mã được (cryptography)", a, H(v["plaintext"]))
    c.eq(f"{n} giải mã được (libsodium)", b, H(v["plaintext"]))
    parsed = _parse_plaintext(H(v["plaintext"]))
    c.eq(f"{n} chan", int(v["chan"], 16), parsed["chan"])
    c.eq(f"{n} more", v["more"], parsed["more"])
    c.eq(f"{n} long", v["long"], parsed["long"])
    c.eq(f"{n} dlen", v["dlen"], parsed["dlen"])
    c.eq(f"{n} data", v["data"], parsed["data"].hex())
    c.true(f"{n} padding toàn 0", parsed["padding"] == bytes(len(parsed["padding"])))
    c.eq(f"{n} rlen đúng tập {{272,1040,4112}}", v["rlen"] in RECORD_SIZES, True)
    c.eq(f"{n} record = rlen(2BE) ‖ ciphertext_tag", H(v["record"]),
         v["rlen"].to_bytes(2, "big") + H(v["ciphertext_tag"]))


def _check_preauth_frame(c, n: str, v: dict) -> None:
    body = H(v["body"])
    kind = int(v["preauth_kind"], 16)
    c.eq(f"{n} byte đầu = kind", body[0], kind)
    c.eq(f"{n} record = rlen(2BE) ‖ body[1:] với kind riêng", H(v["record"]),
         len(body).to_bytes(2, "big") + body)


def _check_negative(c, n: str, v: dict) -> None:
    reason = v["reason"]
    c.true(f"{n} reason nằm trong tập đã định", reason in REASONS)
    if reason == "rlen_out_of_bounds":
        c.true(f"{n} rlen không thuộc {{272,1040,4112}}", v["rlen"] not in RECORD_SIZES)
        c.eq(f"{n} record đúng rlen ghi trong vector", H(v["record"])[:2], v["rlen"].to_bytes(2, "big"))
    elif reason == "preauth_record_over_bound":
        c.true(f"{n} rlen > BT_PREAUTH_RECORD_MAX", v["rlen"] > BT_PREAUTH_RECORD_MAX)
    elif reason == "unknown_chan":
        c.true(f"{n} chan không thuộc {{0x01,0x02}}", int(v["chan"], 16) not in CHAN_VALID)
    elif reason == "more_without_long":
        parsed = _parse_plaintext(H(v["plaintext"]))
        c.true(f"{n} more=1 và long=0", parsed["more"] and not parsed["long"])
    elif reason == "bulk_fragment_over_max":
        c.true(f"{n} dlen > BT_BULK_FRAGMENT_MAX", v["dlen"] > BT_BULK_FRAGMENT_MAX)
    else:  # message_over_max
        c.eq(f"{n} tổng sau mảnh này", v["total_after_fragment"], v["prior_bytes_received"] + v["last_fragment_dlen"])
        c.true(f"{n} tổng vượt BT_MESSAGE_MAX", v["total_after_fragment"] > BT_MESSAGE_MAX)


def check_bt_frame(c, doc: dict, all_docs: dict) -> None:
    link_doc = all_docs["bt-link.json"]
    handshake = next(v for v in link_doc["vectors"] if v["kind"] == "handshake")
    c1 = H(handshake["c1"])
    kinds = set()
    for v in doc["vectors"]:
        n = f"bt-frame/{v['name']}"
        kinds.add(v["kind"])
        if v["kind"] == "transport_frame":
            c.eq(f"{n} key_source là c1 của bt-link.json", v["key_source"], "c1 của bt-link.json")
            _check_transport_frame(c, n, v, c1)
        elif v["kind"] == "preauth_frame":
            _check_preauth_frame(c, n, v)
        else:
            c.true(f"{n} kind {v['kind']!r} không nằm trong tập đã định", False)
    c.eq("bt-frame: có đủ loại vector", kinds, {"transport_frame", "preauth_frame"})
    for v in doc["invalid_vectors"]:
        _check_negative(c, f"bt-frame/{v['name']}", v)
    c.eq("bt-frame: đủ loại vector âm", {v["reason"] for v in doc["invalid_vectors"]}, REASONS)


CHECKS = {"bt-frame.json": check_bt_frame}
