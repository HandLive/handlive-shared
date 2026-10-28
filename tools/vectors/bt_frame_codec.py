"""Mã hoá/giải mã khung Bluetooth (00-common-specs.md 0.4.5 "Link records", "Transport records and channels") —
dùng cho cả phía sinh và phía kiểm (chỉ là phép toán đóng gói byte, không phải thuật toán mật mã, nên không cần
hai cài đặt độc lập — giống cách lv_cat/LEB128 của CPace được chia sẻ)."""

PADDED_SIZES = (256, 1024, 4096)
TAG_LEN = 16
RECORD_SIZES = tuple(p + TAG_LEN for p in PADDED_SIZES)  # 272, 1040, 4112
CHAN_CONTROL, CHAN_BULK = 0x01, 0x02
FLAG_MORE, FLAG_LONG = 0x01, 0x02
PREAUTH_RECORD_MAX = 64


def padded_size(dlen: int) -> int:
    """Cỡ nhỏ nhất trong {256, 1024, 4096} chứa đủ khung chan(1)+flags(1)+dlen(2)+data(dlen) (0.4.5)."""
    frame_len = 4 + dlen
    for size in PADDED_SIZES:
        if frame_len <= size:
            return size
    raise ValueError(f"dlen={dlen} vượt cả 4096 (BT_FRAGMENT_MAX=4092 phải chặn trước khi gọi hàm này)")


def build_frame(chan: int, more: bool, long_lane: bool, data: bytes) -> bytes:
    """chan(1) ‖ flags(1) ‖ dlen(2 BE) ‖ data ‖ padding 0, tới cỡ padded_size(len(data))."""
    flags = (FLAG_MORE if more else 0) | (FLAG_LONG if long_lane else 0)
    header = bytes([chan, flags]) + len(data).to_bytes(2, "big")
    plaintext = header + data
    size = padded_size(len(data))
    return plaintext + bytes(size - len(plaintext))


def parse_frame(plaintext: bytes) -> dict:
    chan, flags = plaintext[0], plaintext[1]
    dlen = int.from_bytes(plaintext[2:4], "big")
    data = plaintext[4:4 + dlen]
    padding = plaintext[4 + dlen:]
    return {"chan": chan, "more": bool(flags & FLAG_MORE), "long": bool(flags & FLAG_LONG), "dlen": dlen,
            "data": data, "padding": padding}


def build_record(rlen_body: bytes) -> bytes:
    """rlen (uint16 BE) ‖ rlen bytes — khung chung cho mọi bản ghi (0.4.5 "Link records")."""
    return len(rlen_body).to_bytes(2, "big") + rlen_body


def build_preauth_record(kind: int, body: bytes) -> bytes:
    return build_record(bytes([kind]) + body)
