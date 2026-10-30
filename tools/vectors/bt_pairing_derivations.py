"""K_bt_pdisc/K_bt_plink và pr_bt (00-common-specs.md 0.4.5 "Keys", "Pairing mode"), dẫn từ `pairing_secret` của
pair-prk.json — dùng để SINH vector."""
from handlive_protocol_derivations import hkdf, hmac256

PDISC_INFO = b"handlive/v1/bt-pair-disc"
PLINK_INFO = b"handlive/v1/bt-pair-link"
PR_BT_LABEL = b"HLBTPAIR1"


def k_bt_pdisc(pairing_secret: bytes) -> bytes:
    """K_bt_pdisc = HKDF-SHA256(ikm = pairing_secret, salt rỗng, info "handlive/v1/bt-pair-disc", L = 32)."""
    return hkdf(pairing_secret, PDISC_INFO, 32)


def k_bt_plink(pairing_secret: bytes) -> bytes:
    """K_bt_plink = HKDF-SHA256(ikm = pairing_secret, salt rỗng, info "handlive/v1/bt-pair-link", L = 32)."""
    return hkdf(pairing_secret, PLINK_INFO, 32)


def pr_bt(pdisc_key: bytes) -> bytes:
    """pr_bt = 4 byte đầu của HMAC-SHA256(K_bt_pdisc, "HLBTPAIR1")."""
    return hmac256(pdisc_key, PR_BT_LABEL)[:4]
