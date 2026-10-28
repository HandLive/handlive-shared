"""Dựng bt-pairing.json: K_bt_pdisc/K_bt_plink, pr_bt (00-common-specs.md 0.4.5 "Keys", "Pairing mode") và một
vector "khung đầu" (first frame) — message 1 của Noise_NNpsk0_25519_ChaChaPoly_SHA256, psk = K_bt_plink — cho một
liên kết ghép đôi QR, cộng các mẫu âm của nó.

Chưa có vector mode PIN (psk = K_bt_plink thay bằng K_bt_pinlink): cpace.json đã có ISK, file này chỉ là chưa
nối vào — xem ghi chú trong `description`.
"""
import bt_pairing_derivations as BT
import noise_nnpsk0 as N
from handlive_protocol_derivations import test_bytes

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
PROLOGUE_LABEL = b"HLBT1"


def _key_vector(pv: dict) -> dict:
    secret = H(pv["pairing_secret"])
    pdisc, plink = BT.k_bt_pdisc(secret), BT.k_bt_plink(secret)
    mac = BT.hmac256(pdisc, BT.PR_BT_LABEL)
    return {"name": pv["name"], "kind": "key", "pair_id": pv["pair_id"], "pairing_secret_source": "pair-prk.json",
            "pairing_secret": secret.hex(), "k_bt_pdisc_info": BT.PDISC_INFO.decode(), "k_bt_pdisc": pdisc.hex(),
            "k_bt_plink_info": BT.PLINK_INFO.decode(), "k_bt_plink": plink.hex(),
            "pr_bt_label": BT.PR_BT_LABEL.decode(), "pr_bt_mac": mac.hex(), "pr_bt": mac[:4].hex()}


def _first_frame_vector(pv: dict, plink: bytes) -> dict:
    n_s = test_bytes(f"bt first-frame n_s {pv['name']}", 32)
    prologue = PROLOGUE_LABEL + n_s
    e_priv = test_bytes(f"bt first-frame e_priv {pv['name']}", 32)
    r = N.first_message(plink, prologue, e_priv)
    opened = N.try_open_first_message(plink, prologue, r["e_pub"], r["ciphertext_tag"])
    assert opened == b"", f"{pv['name']}: khung đầu phải mở được với đúng psk"
    kind, message1 = 0x02, r["message1"]
    rlen = 1 + len(message1)
    record = rlen.to_bytes(2, "big") + bytes([kind]) + message1
    return {"name": f"{pv['name']} / liên kết ghép đôi QR", "kind": "first_frame", "mode": "qr",
            "pair_id": pv["pair_id"], "psk_source": f"k_bt_plink của {pv['name']}", "psk": plink.hex(),
            "protocol_name": r["protocol_name"].decode(), "n_s": n_s.hex(), "prologue_label": PROLOGUE_LABEL.decode(),
            "prologue": prologue.hex(), "h0": r["h0"].hex(), "h_after_prologue": r["h1"].hex(),
            "mix_key_and_hash": {k: v.hex() for k, v in r["mix_key_and_hash"].items()},
            "h_after_psk": r["h2"].hex(), "ck_after_psk": r["ck1"].hex(), "k": r["k"].hex(),
            "e_priv": r["e_priv"].hex(), "e_pub": r["e_pub"].hex(), "h_after_e": r["h3"].hex(),
            "nonce": r["nonce"].hex(), "ciphertext_tag": r["ciphertext_tag"].hex(), "h_final": r["h4"].hex(),
            "message1": message1.hex(), "record_kind": "0x02", "rlen": rlen, "record": record.hex()}


def _negatives(pv1: dict, pv2: dict, plink1: bytes, plink2: bytes, base: dict) -> list[dict]:
    n_s, e_pub, ct = H(base["n_s"]), H(base["e_pub"]), H(base["ciphertext_tag"])
    prologue = H(base["prologue"])
    out = []

    assert N.try_open_first_message(plink2, prologue, e_pub, ct) is None
    out.append({"name": f"{pv1['name']} / S thử psk của {pv2['name']}", "reason": "wrong_key",
                "n_s": base["n_s"], "e_pub": base["e_pub"], "ciphertext_tag": base["ciphertext_tag"],
                "wrong_psk_source": f"k_bt_plink của {pv2['name']}", "wrong_psk": plink2.hex()})

    bad_ct = bytearray(ct)
    bad_ct[-1] ^= 0x01
    assert N.try_open_first_message(plink1, prologue, e_pub, bytes(bad_ct)) is None
    out.append({"name": f"{pv1['name']} / tag sai", "reason": "tag_mismatch", "n_s": base["n_s"],
                "e_pub": base["e_pub"], "ciphertext_tag": bytes(bad_ct).hex()})

    bad_e = bytearray(e_pub)
    bad_e[0] ^= 0x01
    assert N.try_open_first_message(plink1, prologue, bytes(bad_e), ct) is None
    out.append({"name": f"{pv1['name']} / e_pub bị sửa trên đường truyền", "reason": "message_tampered",
                "n_s": base["n_s"], "e_pub": bytes(bad_e).hex(), "ciphertext_tag": base["ciphertext_tag"]})

    other_n_s = test_bytes(f"bt first-frame n_s khác kênh {pv1['name']}", 32)
    assert N.try_open_first_message(plink1, PROLOGUE_LABEL + other_n_s, e_pub, ct) is None
    out.append({"name": f"{pv1['name']} / phát lại message 1 trên kênh khác (n_s khác)", "reason": "aad_mismatch",
                "n_s": other_n_s.hex(), "e_pub": base["e_pub"], "ciphertext_tag": base["ciphertext_tag"]})
    return out


DESCRIPTION = (
    "K_bt_pdisc = HKDF-SHA256(ikm = pairing_secret, salt rỗng, info \"handlive/v1/bt-pair-disc\", L 32); "
    "K_bt_plink = HKDF-SHA256(ikm = pairing_secret, salt rỗng, info \"handlive/v1/bt-pair-link\", L 32); "
    "pr_bt = 4 byte đầu của HMAC-SHA256(K_bt_pdisc, \"HLBTPAIR1\"), đổi theo mỗi QR, không suy ra được pk/ps "
    "(0.4.5 \"Keys\", \"Pairing mode\"). kind \"first_frame\": message 1 (\"psk, e\") của "
    "Noise_NNpsk0_25519_ChaChaPoly_SHA256 (Noise Protocol Framework rev. 34), psk = K_bt_plink, prologue = "
    "\"HLBT1\" ‖ n_s — xác thực \"khung đầu\" của một liên kết ghép đôi trước khi slot pre-auth được cấp (0.4.5 "
    "\"Pairing mode\", \"Link-security handshake\"). HKDF ở đây là HKDF nội bộ của Noise (3 ngõ ra qua HMAC), "
    "khác HKDF-SHA256 RFC 5869 dùng ở các file khác trong kho này. `record` = rlen (uint16 BE) ‖ kind (0x02) ‖ "
    "message1 — đúng khuôn \"Link records\" của 0.4.5. KHÔNG phải vector công bố của tài liệu Noise (tài liệu đó "
    "không phát hành vector cho psk/prologue riêng của HandLive): đây là cách HandLive dùng đúng thuật toán của "
    "tài liệu đó cho bộ psk/prologue của mình, cần Trang rà soát riêng. Chưa có vector mode PIN (psk thay bằng "
    "K_bt_pinlink): cpace.json đã có ISK, chỉ là chưa nối vào, để lại cho một task sau."
)


def build(ctx: dict) -> dict:
    pairs = {p["name"]: p for p in ctx["pairs"]}
    pv1, pv2 = pairs["cặp 1"], pairs["cặp 2"]
    key_vectors = [_key_vector(pv1), _key_vector(pv2)]
    plink = {v["name"]: H(v["k_bt_plink"]) for v in key_vectors}
    first_frame = _first_frame_vector(pv1, plink["cặp 1"])
    negatives = _negatives(pv1, pv2, plink["cặp 1"], plink["cặp 2"], first_frame)
    doc = {"description": DESCRIPTION,
           "source": f"{SPEC} 0.4.5 \"Keys\", \"Pairing mode\", \"Link-security handshake\"; pairing_secret của "
                     "pair-prk.json; Noise Protocol Framework rev. 34 (Noise_NNpsk0_25519_ChaChaPoly_SHA256)",
           "vectors": key_vectors + [first_frame], "invalid_vectors": negatives}
    return {"bt-pairing.json": doc}
