"""Dựng bt-link.json: K_bt_disc/K_bt_link (00-common-specs.md 0.4.5 "Keys"), hint quảng bá xoay vòng, và bắt tay
bảo mật liên kết đầy đủ (`challenge`/`noise1`/`noise2`, psk = `K_bt_link`) cho một liên kết Bluetooth bình thường
(sau khi đã ghép đôi) — khác bt-pairing.json (psk = `K_bt_plink`, chỉ cho liên kết ghép đôi QR).
"""
import bt_frame_codec as F
import bt_link_derivations as BT
import noise_nnpsk0 as N
from handlive_protocol_derivations import test_bytes

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
PROLOGUE_LABEL = b"HLBT1"
BT_HINT_PERIOD_MS = 900_000


def _key_vector(pv: dict) -> dict:
    prk = H(pv["prk"])
    disc, link = BT.k_bt_disc(prk), BT.k_bt_link(prk)
    return {"name": pv["name"], "kind": "key", "pair_id": pv["pair_id"], "prk_source": "pair-prk.json",
            "prk": prk.hex(), "k_bt_disc_info": BT.DISC_INFO.decode(), "k_bt_disc": disc.hex(),
            "k_bt_link_info": BT.LINK_INFO.decode(), "k_bt_link": link.hex()}


def _hint_vector(pv: dict, disc: bytes) -> dict:
    """Hint ở 3 kỷ nguyên liên tiếp: client chấp nhận hint trong khoảng e-4..e+4 (0.4.5 "Advertisement")."""
    epochs = [0, 1, 2, 479762]
    hints = [{"epoch": e, "hint": BT.disc_hint(disc, e).hex()} for e in epochs]
    return {"name": f"{pv['name']} / hint quảng bá", "kind": "hint", "pair_id": pv["pair_id"],
            "k_bt_disc_source": pv["name"], "hint_label": BT.HINT_LABEL.decode(),
            "bt_hint_period_ms": BT_HINT_PERIOD_MS, "epochs": hints}


def _handshake_vector(pv: dict, link: bytes) -> dict:
    n_s = test_bytes(f"bt link n_s {pv['name']}", 32)
    challenge_record = F.build_preauth_record(0x01, n_s)
    prologue = PROLOGUE_LABEL + n_s

    e_priv_c = test_bytes(f"bt link e_priv_c {pv['name']}", 32)
    m1 = N.first_message(link, prologue, e_priv_c)
    opened = N.try_open_first_message(link, prologue, m1["e_pub"], m1["ciphertext_tag"])
    assert opened == b"", f"{pv['name']}: noise1 phải mở được với đúng psk"
    noise1_record = F.build_preauth_record(0x02, m1["message1"])

    e_priv_s = test_bytes(f"bt link e_priv_s {pv['name']}", 32)
    m2 = N.second_message(m1["ck1"], m1["h4"], e_priv_s, m1["e_pub"])
    pt_c, ck2_c, h6_c = N.try_open_second_message(m1["ck1"], m1["h4"], e_priv_c, m2["e_pub"], m2["ciphertext_tag"])
    assert pt_c == b"" and ck2_c == m2["ck2"] and h6_c == m2["h6"], f"{pv['name']}: noise2 phải khớp cả hai phía"
    noise2_record = F.build_preauth_record(0x03, m2["message2"])

    split_s = N.split(m2["ck2"])
    split_c = N.split(ck2_c)
    assert split_s == split_c, f"{pv['name']}: Split() phải khớp cả hai phía"

    return {
        "name": f"{pv['name']} / bắt tay liên kết thường", "kind": "handshake", "pair_id": pv["pair_id"],
        "psk_source": f"k_bt_link của {pv['name']}", "psk": link.hex(), "protocol_name": m1["protocol_name"].decode(),
        "n_s": n_s.hex(), "prologue_label": PROLOGUE_LABEL.decode(), "prologue": prologue.hex(),
        "challenge_kind": "0x01", "challenge_record": challenge_record.hex(),
        "h0": m1["h0"].hex(), "h_after_prologue": m1["h1"].hex(),
        "mix_key_and_hash_psk": {k: v.hex() for k, v in m1["mix_key_and_hash"].items()},
        "h_after_psk": m1["h2"].hex(), "ck_after_psk": m1["ck_after_psk"].hex(),
        "mix_key_e_c": {k: v.hex() for k, v in m1["mix_key_e"].items()},
        "ck_after_e_c": m1["ck1"].hex(), "k_message1": m1["k"].hex(),
        "e_priv_c": m1["e_priv"].hex(), "e_pub_c": m1["e_pub"].hex(), "h_after_e_c": m1["h3"].hex(),
        "ciphertext_tag_1": m1["ciphertext_tag"].hex(), "h_after_message1": m1["h4"].hex(),
        "message1": m1["message1"].hex(), "noise1_kind": "0x02", "noise1_record": noise1_record.hex(),
        "e_priv_s": m2["e_priv"].hex(), "e_pub_s": m2["e_pub"].hex(), "h_after_e_s": m2["h5"].hex(),
        "mix_key_e_s": {k: v.hex() for k, v in m2["mix_key_e"].items()}, "dh_ee": m2["dh"].hex(),
        "mix_key_ee": {k: v.hex() for k, v in m2["mix_key_ee"].items()},
        "ck_after_ee": m2["ck2"].hex(), "k_message2": m2["k"].hex(), "ciphertext_tag_2": m2["ciphertext_tag"].hex(),
        "h_final": m2["h6"].hex(), "message2": m2["message2"].hex(), "noise2_kind": "0x03",
        "noise2_record": noise2_record.hex(), "c1": split_s["c1"].hex(), "c2": split_s["c2"].hex(),
        "c1_note": "c1 mã hoá bởi C (khởi tạo), giải mã bởi S", "c2_note": "c2 mã hoá bởi S, giải mã bởi C",
    }


def _negatives(pv1: dict, pv2: dict, link1: bytes, link2: bytes, hs: dict) -> list[dict]:
    n_s, prologue = H(hs["n_s"]), H(hs["prologue"])
    e_pub_c, ct1 = H(hs["e_pub_c"]), H(hs["ciphertext_tag_1"])
    e_pub_s, ct2 = H(hs["e_pub_s"]), H(hs["ciphertext_tag_2"])
    ck1, h4 = H(hs["ck_after_e_c"]), H(hs["h_after_message1"])
    out = []

    assert N.try_open_first_message(link2, prologue, e_pub_c, ct1) is None
    out.append({"name": f"{pv1['name']} / S thử psk của {pv2['name']}", "reason": "wrong_key", "n_s": hs["n_s"],
                "e_pub_c": hs["e_pub_c"], "ciphertext_tag_1": hs["ciphertext_tag_1"],
                "wrong_psk_source": f"k_bt_link của {pv2['name']}", "wrong_psk": link2.hex()})

    bad_ct1 = bytearray(ct1)
    bad_ct1[-1] ^= 0x01
    assert N.try_open_first_message(link1, prologue, e_pub_c, bytes(bad_ct1)) is None
    out.append({"name": f"{pv1['name']} / tag noise1 sai", "reason": "tag_mismatch_noise1", "n_s": hs["n_s"],
                "e_pub_c": hs["e_pub_c"], "ciphertext_tag_1": bytes(bad_ct1).hex()})

    bad_ct2 = bytearray(ct2)
    bad_ct2[-1] ^= 0x01
    pt_bad, _, _ = N.try_open_second_message(ck1, h4, H(hs["e_priv_c"]), e_pub_s, bytes(bad_ct2))
    assert pt_bad is None
    out.append({"name": f"{pv1['name']} / tag noise2 sai", "reason": "tag_mismatch_noise2", "n_s": hs["n_s"],
                "e_pub_s": hs["e_pub_s"], "ciphertext_tag_2": bytes(bad_ct2).hex()})

    other_n_s = test_bytes(f"bt link n_s kênh khác {pv1['name']}", 32)
    assert N.try_open_first_message(link1, PROLOGUE_LABEL + other_n_s, e_pub_c, ct1) is None
    out.append({"name": f"{pv1['name']} / phát lại noise1 trên kênh khác (n_s khác)", "reason": "replayed_channel",
                "n_s": other_n_s.hex(), "e_pub_c": hs["e_pub_c"], "ciphertext_tag_1": hs["ciphertext_tag_1"]})
    return out


DESCRIPTION = (
    "K_bt_disc = HKDF-SHA256(ikm = PRK, salt rỗng, info \"handlive/v1/bt-discovery\", L 32); K_bt_link (tương tự, "
    "info \"handlive/v1/bt-link\") — sống suốt đời cặp, khác K_bt_pdisc/K_bt_plink của bt-pairing.json (sống theo "
    "một QR). kind \"hint\": hint quảng bá bình thường (không phải lúc ghép đôi) = 4 byte đầu của "
    "HMAC-SHA256(K_bt_disc, \"HLBTDISC1\" ‖ epoch int64 BE), epoch = floor(now_ms / BT_HINT_PERIOD) — khác pr_bt "
    "(đổi theo mỗi QR) vì hint này đổi theo thời gian (0.4.5 \"Advertisement\"). kind \"handshake\": bắt tay bảo "
    "mật liên kết đầy đủ (0.4.5 \"Link-security handshake\" bước 1-4), psk = K_bt_link: challenge (kind 0x01, n_s "
    "32 byte) rồi message 1 (\"psk, e\", kind 0x02 noise1) và message 2 (\"e, ee\", kind 0x03 noise2) của "
    "Noise_NNpsk0_25519_ChaChaPoly_SHA256 (Noise Protocol Framework rev. 34), prologue = \"HLBT1\" ‖ n_s, rồi "
    "Split() ra c1 (C mã hoá/S giải mã)/c2 (ngược lại) — hai CipherState của bước 4-5. KHÔNG phải vector công bố "
    "của tài liệu Noise (xem ghi chú ở bt-pairing.json); noise_nnpsk0.py đã được Trang rà soát ở #3328 cho message "
    "1, cần rà soát thêm phần message 2/Split mới. invalid_vectors: wrong_key, tag_mismatch_noise1, "
    "tag_mismatch_noise2 (0.4.5 bước 4: 'C verifies its payload tag — failure → C closes the channel, CONN-05 E3'), "
    "replayed_channel (0.4.5 bước 3: 'The prologue binds n_s, so a recorded noise1 never verifies on a new "
    "channel')."
)


def build(ctx: dict) -> dict:
    pairs = {p["name"]: p for p in ctx["pairs"]}
    pv1, pv2 = pairs["cặp 1"], pairs["cặp 2"]
    key_vectors = [_key_vector(pv1), _key_vector(pv2)]
    disc = {v["name"]: H(v["k_bt_disc"]) for v in key_vectors}
    link = {v["name"]: H(v["k_bt_link"]) for v in key_vectors}
    hint_vectors = [_hint_vector(pv1, disc["cặp 1"])]
    handshake = _handshake_vector(pv1, link["cặp 1"])
    negatives = _negatives(pv1, pv2, link["cặp 1"], link["cặp 2"], handshake)
    doc = {"description": DESCRIPTION,
           "source": f"{SPEC} 0.4.5 \"Keys\", \"Advertisement\", \"Link-security handshake\"; PRK của "
                     "pair-prk.json; Noise Protocol Framework rev. 34 (Noise_NNpsk0_25519_ChaChaPoly_SHA256)",
           "vectors": key_vectors + hint_vectors + [handshake], "invalid_vectors": negatives}
    return {"bt-link.json": doc}
