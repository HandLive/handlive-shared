"""Kiểm chéo bắt tay Noise_NNpsk0_25519_ChaChaPoly_SHA256 trên vector `handshake` của bt-link.json bằng
`noiseprotocol` (PyPI, pin ở tools/vectors/requirements.txt) — thư viện Noise ĐỘC LẬP HOÀN TOÀN với
noise_nnpsk0.py (không chỉ đổi primitive như verify_bt_link_checks.py, mà chạy lại chính thuật toán Noise bằng
mã người khác viết), theo ghi chú của Trang ở #3328 và yêu cầu của Lead ở #3376/#3380.

THEO YÊU CẦU CỦA LEAD: thiếu `noiseprotocol` phải báo lỗi rõ, không âm thầm bỏ qua — môi trường chưa chạy
`pip install -r requirements.txt` (có `noiseprotocol==0.3.1`) sẽ thấy lỗi ImportError ở đây, không phải một dòng
"bỏ qua" lặng lẽ.

Chưa tự chạy được trong sandbox của Tuan (không có mạng để pip install) — ghi lại trong task #189: cần chạy sau
khi `tools/setup-cpace-refs.sh` cài xong `noiseprotocol` để xác nhận API dưới đây (từ hiểu biết về thư viện,
chưa tự kiểm) khớp với phiên bản 0.3.1 thật.
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
