"""CPACE-X25519-SHA512 (draft-irtf-cfrg-cpace-21, suite G_X25519 + SHA-512): calculate_generator (Elligator2,
Appendix A.5), message A/B, K, ISK khởi tạo/trả lời (Appendix A.3.4, section 7.2). HandLive dùng suite này cho
ghép đôi bằng PIN qua Bluetooth không mạng (00-common-specs.md 0.4.5, luồng C): C khởi tạo (gửi `cpace1`), S trả
lời (gửi `cpace2`), nên chỉ cần `transcript_ir`/`isk` (khởi tạo/trả lời), không cần biến thể song hành (`_oc`).

Kiểm end-to-end khớp byte-exact với vector B.1 của draft (`cpace_source_values.py`); `verify_vectors.py` kiểm lại
bằng pynacl (độc lập với `cryptography` dùng ở đây).
"""
import hashlib

from cryptography.hazmat.primitives.asymmetric import x25519

DSI = b"CPace255"
DSI_ISK = DSI + b"_ISK"
H_S_IN_BYTES = 128  # kích thước khối nhập của SHA-512
FIELD_SIZE_BYTES = 32
FIELD_SIZE_BITS = 255
Q_25519 = 2 ** 255 - 19
A_25519 = 486662
Z_25519 = 2  # find_z_ell2(GF(2^255 - 19)) cho Curve25519 (Appendix A.5)


def prepend_len(data: bytes) -> bytes:
    """LEB128 độ dài ‖ data (Appendix A.1.1)."""
    length, encoded = len(data), bytearray()
    while True:
        encoded.append(length if length < 128 else (length & 0x7F) + 0x80)
        length >>= 7
        if length == 0:
            break
    return bytes(encoded) + data


def lv_cat(*parts: bytes) -> bytes:
    """"length-value": nối các chuỗi, mỗi chuỗi có độ dài LEB128 đặt trước (Appendix A.1.3)."""
    return b"".join(prepend_len(p) for p in parts)


def generator_string(prs: bytes, ci: bytes, sid: bytes, s_in_bytes: int = H_S_IN_BYTES, dsi: bytes = DSI) -> bytes:
    """Appendix A.2: lv_cat(DSI, PRS, zero_bytes(len_zpad), CI, sid) — đệm 0 để DSI‖PRS lấp đầy khối băm đầu
    tiên, làm độ dài băm độc lập với độ dài PRS thật (chống side-channel qua độ dài)."""
    len_zpad = max(0, s_in_bytes - 1 - len(prepend_len(prs)) - len(prepend_len(dsi)))
    return lv_cat(dsi, prs, bytes(len_zpad), ci, sid)


def decode_u_coordinate(u: bytes, bits: int = FIELD_SIZE_BITS) -> int:
    """RFC 7748 decodeUCoordinate (Appendix A.4): xoá bit không dùng của byte cuối (mảng little-endian)."""
    u_list = bytearray(u)
    if bits % 8:
        u_list[-1] &= (1 << (bits % 8)) - 1
    return int.from_bytes(bytes(u_list), "little")


def _encode_u_coordinate(u: int, bits: int = FIELD_SIZE_BITS) -> bytes:
    return u.to_bytes((bits + 7) // 8, "little")


def elligator2_x25519(r: int) -> bytes:
    """Appendix A.5 (map_to_curve_elligator2), A = 486662 và Z = 2 của Curve25519 — chuyển một phần tử trường r
    (nguyên, đã decode_u_coordinate) thành toạ độ u hợp lệ của một điểm trên đường cong."""
    q, a = Q_25519, A_25519 % Q_25519
    z = Z_25519 % q
    power = (q - 1) // 2
    denom = (1 + z * r * r) % q
    v = (-a * pow(denom, q - 2, q)) % q
    rhs = (pow(v, 3, q) + a * pow(v, 2, q) + v) % q
    epsilon = pow(rhs, power, q)
    if epsilon == q - 1:
        epsilon = -1
    x = (epsilon * v - (1 - epsilon) * a * pow(2, q - 2, q)) % q
    return _encode_u_coordinate(x)


def calculate_generator(prs: bytes, ci: bytes, sid: bytes) -> bytes:
    """G.calculate_generator(SHA-512, PRS, CI, sid) của G_X25519 (0.4.5: `g` = calculate_generator(...))."""
    gen_str_hash = hashlib.sha512(generator_string(prs, ci, sid)).digest()[:FIELD_SIZE_BYTES]
    return elligator2_x25519(decode_u_coordinate(gen_str_hash))


def scalar_mult_vfy(scalar: bytes, point: bytes) -> bytes | None:
    """G_X25519.scalar_mult_vfy = X25519(scalar, point); None (G.I — phải abort) khi `point` là điểm bậc thấp.
    `cryptography` lên tiếng bằng ValueError đúng khi và chỉ khi kết quả là phần tử trung hoà (đã đối chiếu với
    12 điểm bậc thấp của Appendix B.1.10, bất kể vô hướng), nên bắt ValueError đúng với "một K toàn 0 → đóng kênh
    không trả lời" (0.4.5, luồng C)."""
    try:
        priv = x25519.X25519PrivateKey.from_private_bytes(scalar)
        pub = x25519.X25519PublicKey.from_public_bytes(point)
        return priv.exchange(pub)
    except ValueError:
        return None


def transcript_ir(ya_pub: bytes, ada: bytes, yb_pub: bytes, adb: bytes) -> bytes:
    """Appendix A.3.4 — thứ tự khởi tạo/trả lời cố định; HandLive luôn có vai rõ (C khởi tạo, S trả lời)."""
    return lv_cat(ya_pub, ada) + lv_cat(yb_pub, adb)


def isk(sid: bytes, k: bytes, ya_pub: bytes, ada: bytes, yb_pub: bytes, adb: bytes) -> bytes:
    """ISK = SHA-512(lv_cat(DSI ‖ "_ISK", sid, K) ‖ transcript_ir(Ya,ADa,Yb,ADb)) (section 7.2)."""
    return hashlib.sha512(lv_cat(DSI_ISK, sid, k) + transcript_ir(ya_pub, ada, yb_pub, adb)).digest()


def run_both_sides(prs: bytes, ci: bytes, sid: bytes, ya: bytes, ada: bytes, yb: bytes, adb: bytes) -> dict:
    """Chạy cả hai vai với đầu vào cho trước (dùng để sinh vector): trả g, Ya, Yb, k_a (phía C), k_b (phía S),
    isk_a, isk_b. `k_a`/`k_b`/`isk_a`/`isk_b` là None khi vai đó phải abort (điểm nhận được bậc thấp)."""
    g = calculate_generator(prs, ci, sid)
    ya_pub = scalar_mult_vfy(ya, g)
    yb_pub = scalar_mult_vfy(yb, g)
    k_a = scalar_mult_vfy(ya, yb_pub) if ya_pub is not None and yb_pub is not None else None
    k_b = scalar_mult_vfy(yb, ya_pub) if ya_pub is not None and yb_pub is not None else None
    isk_a = isk(sid, k_a, ya_pub, ada, yb_pub, adb) if k_a is not None else None
    isk_b = isk(sid, k_b, ya_pub, ada, yb_pub, adb) if k_b is not None else None
    return {"g": g, "Ya": ya_pub, "Yb": yb_pub, "k_a": k_a, "k_b": k_b, "isk_a": isk_a, "isk_b": isk_b}
