"""Kiểm chéo bắt tay Noise_NNpsk0_25519_ChaChaPoly_SHA256 trên vector `handshake` của bt-link.json bằng
`noiseprotocol` (PyPI, pin ở tools/vectors/requirements.txt) — thư viện Noise ĐỘC LẬP HOÀN TOÀN với
noise_nnpsk0.py (không chỉ đổi primitive như verify_bt_link_checks.py, mà chạy lại chính thuật toán Noise bằng
mã người khác viết), theo ghi chú của Trang ở #3328 và yêu cầu của Lead ở #3376/#3380. Đã tự chạy thật (Lead cài
`noiseprotocol` qua `setup-cpace-refs.sh`, #3412): bắt đúng lỗi thiếu MixKey(e.pub) của chế độ psk (#3418), sau
khi vá noise_nnpsk0.py thì `message1`, `message2`, `handshake_hash` và cả hai khoá `Split()` (`cipher_state_encrypt.k`/
`cipher_state_decrypt.k`) đều khớp byte-exact với `noiseprotocol`.

THEO YÊU CẦU CỦA LEAD: thiếu `noiseprotocol` phải báo lỗi rõ, không âm thầm bỏ qua — môi trường chưa chạy
`pip install -r requirements.txt` (có `noiseprotocol==0.3.1`) sẽ thấy lỗi ImportError ở đây, không phải một dòng
"bỏ qua" lặng lẽ.
"""
from verify_common import H

PROTOCOL_NAME = "Noise_NNpsk0_25519_ChaChaPoly_SHA256"


def _side(role: str, psk: bytes, prologue: bytes, e_priv: bytes):
    from noise.connection import Keypair, NoiseConnection  # import trong hàm: báo lỗi rõ đúng tại bước này,
    # không chặn mọi phép kiểm khác của verify_vectors.py khi thiếu thư viện (xem lời gọi trong verify_vectors.py).
    conn = NoiseConnection.from_name(PROTOCOL_NAME.encode())
    conn.set_as_initiator() if role == "initiator" else conn.set_as_responder()
    conn.set_psks(psk)
    conn.set_prologue(prologue)
    conn.set_keypair_from_private_bytes(Keypair.EPHEMERAL, e_priv)
    conn.start_handshake()
    return conn


def check_bt_link_with_noiseprotocol(c, doc: dict, all_docs: dict) -> None:
    handshake = next(v for v in doc["vectors"] if v["kind"] == "handshake")
    n = f"bt-link/noiseprotocol/{handshake['name']}"
    psk, prologue = H(handshake["psk"]), H(handshake["prologue"])
    e_priv_c, e_priv_s = H(handshake["e_priv_c"]), H(handshake["e_priv_s"])

    initiator = _side("initiator", psk, prologue, e_priv_c)
    responder = _side("responder", psk, prologue, e_priv_s)

    message1 = initiator.write_message(b"")
    c.eq(f"{n} message1 (noiseprotocol khởi tạo)", message1, H(handshake["message1"]))
    responder.read_message(message1)

    message2 = responder.write_message(b"")
    c.eq(f"{n} message2 (noiseprotocol trả lời)", message2, H(handshake["message2"]))
    initiator.read_message(message2)

    c.true(f"{n} cả hai phía xong bắt tay", initiator.handshake_finished and responder.handshake_finished)
    c.eq(f"{n} handshake_hash (h6) cả hai phía", initiator.noise_protocol.handshake_hash,
         responder.noise_protocol.handshake_hash)
    c.eq(f"{n} handshake_hash (h6) khớp vector", initiator.noise_protocol.handshake_hash, H(handshake["h_final"]))
    c.eq(f"{n} Split() c1 (C mã hoá/S giải mã)", initiator.noise_protocol.cipher_state_encrypt.k,
         H(handshake["c1"]))
    c.eq(f"{n} Split() c1 khớp phía S", responder.noise_protocol.cipher_state_decrypt.k, H(handshake["c1"]))
    c.eq(f"{n} Split() c2 (S mã hoá/C giải mã)", responder.noise_protocol.cipher_state_encrypt.k,
         H(handshake["c2"]))
    c.eq(f"{n} Split() c2 khớp phía C", initiator.noise_protocol.cipher_state_decrypt.k, H(handshake["c2"]))
