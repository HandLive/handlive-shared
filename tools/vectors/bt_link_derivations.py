"""K_bt_disc/K_bt_link dẫn từ `PRK` của pair-prk.json (00-common-specs.md 0.4.5 "Keys") — dùng để SINH vector.
Khác `K_bt_pdisc`/`K_bt_plink` (bt_pairing_derivations.py, dẫn từ `pairing_secret`, chỉ sống trong một QR): các
khoá này sống suốt đời cặp, dùng cho liên kết Bluetooth bình thường sau khi đã ghép đôi."""
from handlive_protocol_derivations import hkdf, hmac256

DISC_INFO = b"handlive/v1/bt-discovery"
LINK_INFO = b"handlive/v1/bt-link"
HINT_LABEL = b"HLBTDISC1"


def k_bt_disc(prk: bytes) -> bytes:
    """K_bt_disc = HKDF-SHA256(ikm = PRK, salt rỗng, info "handlive/v1/bt-discovery", L = 32)."""
    return hkdf(prk, DISC_INFO, 32)


def k_bt_link(prk: bytes) -> bytes:
    """K_bt_link = HKDF-SHA256(ikm = PRK, salt rỗng, info "handlive/v1/bt-link", L = 32)."""
    return hkdf(prk, LINK_INFO, 32)


def disc_hint(k_bt_disc_key: bytes, epoch: int) -> bytes:
    """hint quảng bá = 4 byte đầu của HMAC-SHA256(K_bt_disc, "HLBTDISC1" ‖ epoch int64 BE) (0.4.5 "Advertisement")."""
    msg = HINT_LABEL + epoch.to_bytes(8, "big", signed=True)
    return hmac256(k_bt_disc_key, msg)[:4]
