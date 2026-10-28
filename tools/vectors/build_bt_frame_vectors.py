"""Dựng bt-frame.json: khung bản ghi transport (chan/flags/dlen/data/padding, 0.4.5 "Transport records and
channels") mã hoá bằng `c1` của bt-link.json (Noise transport message, nonce = bộ đếm 64-bit LE), cùng mẫu âm cho
từng luật cận mà A7.1a/M7.1b phải chặn: `rlen` ngoài {272, 1 040, 4 112}, `chan` lạ, `more` không có `long`, một
mảnh làn dài vượt `BT_BULK_FRAGMENT_MAX`, một tin làn dài vượt `BT_MESSAGE_MAX` trước mảnh cuối, một bản ghi
pre-auth vượt `BT_PREAUTH_RECORD_MAX`.
"""
import bt_frame_codec as F
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from handlive_protocol_derivations import test_bytes

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md"
BT_FRAGMENT_MAX = 4092
BT_BULK_FRAGMENT_MAX = 1020
BT_MESSAGE_MAX = 256 * 1024
BT_PREAUTH_RECORD_MAX = 64


def _nonce(counter: int) -> bytes:
    return bytes(4) + counter.to_bytes(8, "little")


def _encrypt(key: bytes, counter: int, plaintext: bytes) -> bytes:
    return ChaCha20Poly1305(key).encrypt(_nonce(counter), plaintext, b"")


def _frame_vector(name: str, chan: int, more: bool, long_lane: bool, data: bytes, key: bytes, counter: int) -> dict:
    plaintext = F.build_frame(chan, more, long_lane, data)
    ciphertext_tag = _encrypt(key, counter, plaintext)
    record = F.build_record(ciphertext_tag)
    return {"name": name, "kind": "transport_frame", "chan": f"0x{chan:02x}", "more": more, "long": long_lane,
            "dlen": len(data), "data": data.hex(), "plaintext": plaintext.hex(), "padded_size": len(plaintext),
            "key_source": "c1 của bt-link.json", "counter": counter, "nonce": _nonce(counter).hex(),
            "ciphertext_tag": ciphertext_tag.hex(), "rlen": len(ciphertext_tag), "record": record.hex()}


def _preauth_vectors() -> list[dict]:
    challenge_body = bytes([0x01]) + test_bytes("bt frame preauth example n_s", 32)
    reject_body = bytes([0x7F])
    return [
        {"name": "challenge (ví dụ đóng gói)", "kind": "preauth_frame", "preauth_kind": "0x01",
         "body": challenge_body.hex(), "record": F.build_preauth_record(0x01, challenge_body[1:]).hex()},
        {"name": "reject (ví dụ đóng gói, thân rỗng)", "kind": "preauth_frame", "preauth_kind": "0x7F",
         "body": reject_body.hex(), "record": F.build_preauth_record(0x7F, b"").hex()},
    ]


def _negatives(key: bytes) -> list[dict]:
    out = []

    good_plain = F.build_frame(F.CHAN_CONTROL, False, False, test_bytes("bt frame rlen_over_bound data", 100))
    good_ct = _encrypt(key, 900, good_plain)
    assert len(good_ct) in F.RECORD_SIZES
    bad_rlen_body = good_ct + b"\x00"  # 273, không nằm trong {272,1040,4112}
    out.append({"name": "rlen ngoài {272,1040,4112}", "reason": "rlen_out_of_bounds",
                "rlen": len(bad_rlen_body), "record": F.build_record(bad_rlen_body).hex(),
                "expect": "rlen không khớp 272/1040/4112 → đóng kênh ngay, không cấp phát đọc tiếp thân bản ghi"})

    preauth_body = bytes([0x01]) + test_bytes("bt frame preauth_over_bound", BT_PREAUTH_RECORD_MAX)
    assert len(preauth_body) == BT_PREAUTH_RECORD_MAX + 1 > BT_PREAUTH_RECORD_MAX
    out.append({"name": "bản ghi pre-auth vượt BT_PREAUTH_RECORD_MAX",
                "reason": "preauth_record_over_bound", "rlen": len(preauth_body),
                "record": F.build_record(preauth_body).hex(), "bt_preauth_record_max": BT_PREAUTH_RECORD_MAX,
                "expect": f"rlen = {len(preauth_body)} > BT_PREAUTH_RECORD_MAX ({BT_PREAUTH_RECORD_MAX}) → đóng "
                          "kênh ngay, không cấp phát"})

    bad_chan_plain = bytes([0x03, 0x00]) + (0).to_bytes(2, "big") + bytes(252)
    bad_chan_ct = _encrypt(key, 901, bad_chan_plain)
    out.append({"name": "chan lạ (không 0x01/0x02)", "reason": "unknown_chan", "chan": "0x03",
                "plaintext": bad_chan_plain.hex(), "record": F.build_record(bad_chan_ct).hex(),
                "expect": "chan = 0x03 không phải 0x01 (control) hay 0x02 (bulk) → đóng liên kết"})

    more_no_long_plain = bytes([F.CHAN_CONTROL, F.FLAG_MORE]) + (10).to_bytes(2, "big") + \
        test_bytes("bt frame more_without_long", 10) + bytes(256 - 14)
    more_no_long_ct = _encrypt(key, 902, more_no_long_plain)
    out.append({"name": "more=1 nhưng long=0 (làn ngắn)", "reason": "more_without_long",
                "plaintext": more_no_long_plain.hex(), "record": F.build_record(more_no_long_ct).hex(),
                "expect": "làn ngắn (long=0) không bao giờ có more=1 (một làn ngắn luôn đúng một mảnh) → đóng "
                          "liên kết"})

    over_fragment_data = test_bytes("bt frame bulk_fragment_over_max data", BT_BULK_FRAGMENT_MAX + 1)
    out.append({"name": f"mảnh làn dài có dlen > BT_BULK_FRAGMENT_MAX ({BT_BULK_FRAGMENT_MAX})",
                "reason": "bulk_fragment_over_max", "chan": "0x01", "long": True,
                "dlen": len(over_fragment_data), "bt_bulk_fragment_max": BT_BULK_FRAGMENT_MAX,
                "expect": f"dlen = {len(over_fragment_data)} > BT_BULK_FRAGMENT_MAX ({BT_BULK_FRAGMENT_MAX}) trên "
                          "làn dài (long=1) hoặc làn bulk (chan=0x02) → đóng liên kết, không cần giải mã thân"})

    prior = BT_MESSAGE_MAX - 500
    last_fragment_dlen = BT_BULK_FRAGMENT_MAX
    out.append({"name": "tin làn dài vượt BT_MESSAGE_MAX trước mảnh cuối", "reason": "message_over_max",
                "chan": "0x01", "long": True, "bt_message_max": BT_MESSAGE_MAX,
                "prior_bytes_received": prior, "last_fragment_dlen": last_fragment_dlen,
                "total_after_fragment": prior + last_fragment_dlen,
                "expect": f"{prior} + {last_fragment_dlen} = {prior + last_fragment_dlen} > BT_MESSAGE_MAX "
                          f"({BT_MESSAGE_MAX}) trước khi mảnh này là mảnh cuối (more=0) → đóng liên kết"})
    return out


DESCRIPTION = (
    "Khung bản ghi pre-auth (`rlen` uint16 BE ‖ `rlen` byte, kind đầu tiên của thân — 0.4.5 \"Link records\") và "
    "khung control/bulk sau bước 4 (chan(1) ‖ flags(1, bit0 more/bit1 long) ‖ dlen(2 BE) ‖ data ‖ 0-padding tới "
    "256/1 024/4 096 byte, mã hoá Noise transport = ChaCha20-Poly1305(key, nonce = 4 zero ‖ bộ đếm 64-bit LE, "
    "AAD rỗng) ‖ tag 16 byte — rlen hợp lệ duy nhất 272/1 040/4 112). `key_source` = `c1` của bt-link.json (hướng "
    "C→S của cùng bắt tay). invalid_vectors khớp đúng 6 luật cận của 0.4.5/S7.1a: rlen_out_of_bounds (rlen không "
    "thuộc {272,1040,4112} → đóng kênh trước khi cấp phát đọc thêm), preauth_record_over_bound (bản ghi pre-auth "
    "vượt BT_PREAUTH_RECORD_MAX = 64 byte), unknown_chan (chan khác 0x01/0x02), more_without_long (more=1 trên "
    "làn ngắn, long=0), bulk_fragment_over_max (dlen một mảnh làn dài/bulk vượt BT_BULK_FRAGMENT_MAX = 1 020), "
    "message_over_max (tổng byte một tin làn dài vượt BT_MESSAGE_MAX = 256 KiB trước mảnh cuối)."
)


def build(ctx: dict, files: dict) -> dict:
    link_doc = files["bt-link.json"]
    handshake = next(v for v in link_doc["vectors"] if v["kind"] == "handshake")
    c1 = H(handshake["c1"])

    short_data = test_bytes("bt frame short control example", 40)
    short_vec = _frame_vector("control / làn ngắn (long=0, 1 mảnh)", F.CHAN_CONTROL, False, False, short_data,
                               c1, 10)

    long_data_1 = test_bytes("bt frame long control example 1", BT_BULK_FRAGMENT_MAX)
    long_vec_1 = _frame_vector("control / làn dài, mảnh 1/2 (more=1, long=1)", F.CHAN_CONTROL, True, True,
                                long_data_1, c1, 11)
    long_data_2 = test_bytes("bt frame long control example 2", 400)
    long_vec_2 = _frame_vector("control / làn dài, mảnh 2/2 cuối (more=0, long=1)", F.CHAN_CONTROL, False, True,
                                long_data_2, c1, 12)

    bulk_data = test_bytes("bt frame bulk example", BT_BULK_FRAGMENT_MAX)
    bulk_vec = _frame_vector("bulk / một mảnh ảnh (more=1)", F.CHAN_BULK, True, False, bulk_data, c1, 13)

    vectors = [short_vec, long_vec_1, long_vec_2, bulk_vec] + _preauth_vectors()
    negatives = _negatives(c1)
    doc = {"description": DESCRIPTION,
           "source": f"{SPEC} 0.4.5 \"Link records\", \"Transport records and channels\"; c1 của bt-link.json",
           "vectors": vectors, "invalid_vectors": negatives}
    return {"bt-frame.json": doc}
