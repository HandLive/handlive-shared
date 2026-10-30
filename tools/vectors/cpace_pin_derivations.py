"""K_bt_pinlink/K_bt_pin dẫn từ ISK của CPace (00-common-specs.md 0.4.5 "PIN", "Keys from ISK") — dùng để SINH
vector. `salt` = `n_s` (cũng là `sid` của CPace), không phải salt rỗng như K_bt_pdisc/K_bt_plink."""
from handlive_protocol_derivations import hkdf

PINLINK_INFO = b"handlive/v1/bt-pin-link"
PIN_INFO = b"handlive/v1/bt-pin-pair"


def k_bt_pinlink(isk: bytes, n_s: bytes) -> bytes:
    """K_bt_pinlink = HKDF-SHA256(ikm = ISK, salt = n_s, info = "handlive/v1/bt-pin-link", L = 32)."""
    return hkdf(isk, PINLINK_INFO, 32, salt=n_s)


def k_bt_pin(isk: bytes, n_s: bytes) -> bytes:
    """K_bt_pin = HKDF-SHA256(ikm = ISK, salt = n_s, info = "handlive/v1/bt-pin-pair", L = 32)."""
    return hkdf(isk, PIN_INFO, 32, salt=n_s)
