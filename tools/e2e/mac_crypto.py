"""Crypto of the fake Mac: identity, PIN pairing (PAIR-01 A1–A5), session handshake (0.6.3), envelopes (0.5.1).

Every derivation comes from the vector tools (tools/vectors), the code behind shared/test-vectors, so the harness
computes exactly what the vectors pin down; self_test.py replays the vectors through this module.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vectors"))

import pairing_discovery_derivations as P  # noqa: E402
from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from handlive_protocol_derivations import (  # noqa: E402
    b64, b64u, compact_json, device_id_from_pub, ed25519_pub, ed25519_sign, envelope_aad, hkdf, hmac256,
    pair_salt_input, uuid_bytes, x25519_dh, x25519_pub, xchacha_seal)
from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt  # noqa: E402
from nacl.exceptions import CryptoError  # noqa: E402

PAIR_INFO = b"handlive/v1/pair"
SESSION_AUTH_INFO = b"handlive/v1/session-auth"
SESSION_INFO = b"handlive/v1/session"
PUSH_INFO = b"handlive/v1/push"
NONCE_LEN = 24
TAG_LEN = 16


def b64u_decode(text: str, length: int | None = None) -> bytes:
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if length is not None and len(raw) != length:
        raise ValueError(f"expected {length} bytes, got {len(raw)}")
    return raw


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def uuid7(ts_ms: int | None = None) -> str:
    """UUIDv7 (RFC 9562): 48-bit ms timestamp, version 7, variant 10, the rest random."""
    ts = now_ms() if ts_ms is None else ts_ms
    raw = bytearray(ts.to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def new_pin() -> str:
    """PAIR-01 A2: six digits from a CSPRNG, uniformly distributed, leading zeros kept."""
    return f"{secrets.randbelow(1_000_000):06d}"


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """0.6.5: exactly 64 bytes; OpenSSL rejects a non-canonical S."""
    if len(signature) != 64:
        return False
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except InvalidSignature:
        return False


@dataclass
class Identity:
    """ik_sig (Ed25519 seed) and ik_dh (X25519 private key) of the fake client, 0.6.1."""
    sig_seed: bytes
    dh_priv: bytes

    @classmethod
    def generate(cls) -> "Identity":
        return cls(os.urandom(32), os.urandom(32))

    @property
    def sig_pub(self) -> bytes:
        return ed25519_pub(self.sig_seed)

    @property
    def dh_pub(self) -> bytes:
        return x25519_pub(self.dh_priv)

    @property
    def device_id(self) -> str:
        return device_id_from_pub(self.sig_pub)

    def sign(self, message: bytes) -> bytes:
        return ed25519_sign(self.sig_seed, message)


@dataclass
class PinOfferCheck:
    """Result of checking `pair/offer` with our PIN (API 3 logic 3 order: mac → device_id → tls_sha256)."""
    ok: bool
    reason: str = ""
    k_pin: bytes = b""
    k_pa: bytes = b""
    t_offer: bytes = b""


def check_pin_offer(pin: str, identity: Identity, name: str, nonce_c: bytes, offer: dict,
                    tls_seen: bytes | None) -> PinOfferCheck:
    """K_pin = Argon2id(PIN, nonce_c ‖ nonce_s); K_pa = HKDF(K_pin, salt nonce_c ‖ nonce_s); mac over T_offer."""
    nonce_s = b64u_decode(offer["nonce"], 32)
    a_sig, a_dh = b64u_decode(offer["ik_sig_pub"], 32), b64u_decode(offer["ik_dh_pub"], 32)
    tls = b64u_decode(offer["tls_sha256"], 32)
    k_pin = P.pin_key(pin, nonce_c, nonce_s)
    k_pa = P.pair_auth_key(k_pin, nonce_c, nonce_s)
    client = {"device_id": identity.device_id, "nonce": nonce_c, "ik_sig_pub": identity.sig_pub,
              "ik_dh_pub": identity.dh_pub, "name": name}
    server = {"device_id": offer["device_id"], "nonce": nonce_s, "ik_sig_pub": a_sig, "ik_dh_pub": a_dh,
              "name": offer["name"]}
    t_offer = P.joined(P.offer_parts(client, server, tls))
    if not hmac.compare_digest(P.hmac_sha256(k_pa, t_offer), b64u_decode(offer["mac"], 32)):
        return PinOfferCheck(False, "mac")
    if device_id_from_pub(a_sig) != offer["device_id"]:
        return PinOfferCheck(False, "device_id")
    if tls_seen is not None and not hmac.compare_digest(tls, tls_seen):
        return PinOfferCheck(False, "tls_sha256")
    return PinOfferCheck(True, "", k_pin, k_pa, t_offer)


@dataclass
class PairSecrets:
    """Everything `pair/confirm` needs and the pair record keeps (API 4, 0.6.2)."""
    pair_id: str
    created_at: int
    prk: bytes
    attestation: bytes
    sig_c: bytes
    confirm: dict = field(default_factory=dict)


def build_confirm(identity: Identity, offer: dict, check: PinOfferCheck, pair_id: str | None = None,
                  created_at: int | None = None) -> PairSecrets:
    a_id, a_sig, a_dh = offer["device_id"], b64u_decode(offer["ik_sig_pub"], 32), b64u_decode(offer["ik_dh_pub"], 32)
    pair_id = pair_id or str(uuid.uuid4())
    created_at = now_ms() if created_at is None else created_at
    shared = x25519_dh(identity.dh_priv, a_dh)
    prk = hkdf(shared + check.k_pin, PAIR_INFO, 32, hashlib.sha256(pair_salt_input(identity.device_id, a_id)).digest())
    attestation = P.joined(P.attestation_parts(pair_id, a_id, identity.device_id, a_sig, identity.sig_pub, created_at))
    sig_c = identity.sign(attestation)
    mac = P.hmac_sha256(check.k_pa, P.joined(P.confirm_parts(check.t_offer, pair_id, created_at, sig_c)))
    confirm = {"pair_id": pair_id, "created_at": created_at, "sig": b64u(sig_c),
               "prk_check": b64u(P.hmac_sha256(prk, P.prk_check_input("client", pair_id))), "mac": b64u(mac)}
    return PairSecrets(pair_id, created_at, prk, attestation, sig_c, confirm)


def check_done(done: dict, offer: dict, check: PinOfferCheck, secrets_: PairSecrets) -> str:
    """API 5 logic 1: mac, prk_check, sig; returns "" when valid, otherwise the failed check."""
    sig_s = b64u_decode(done["sig"], 64)
    mac = P.hmac_sha256(check.k_pa, P.joined(P.done_parts(secrets_.pair_id, sig_s)))
    if not hmac.compare_digest(mac, b64u_decode(done["mac"], 32)):
        return "mac"
    expected = P.hmac_sha256(secrets_.prk, P.prk_check_input("server", secrets_.pair_id))
    if not hmac.compare_digest(expected, b64u_decode(done["prk_check"], 32)):
        return "prk_check"
    if not ed25519_verify(b64u_decode(offer["ik_sig_pub"], 32), secrets_.attestation, sig_s):
        return "sig"
    return ""


def security_code(attestation: bytes) -> str:
    """PAIR-02 field 10: the first 8 lowercase hex digits of SHA-256(attestation)."""
    return P.security_code(attestation)


@dataclass
class HelloKeys:
    eph_priv: bytes
    nonce: bytes
    t1: bytes
    data: dict


def session_hello(prk: bytes, pair_id: str, client_id: str, eph_priv: bytes | None = None,
                  nonce: bytes | None = None) -> HelloKeys:
    """0.6.3 step 1: T1 = "HL1|hello|" ‖ pair_id ‖ device_id C ‖ eph C ‖ nonce C (106 bytes)."""
    eph_priv = eph_priv or os.urandom(32)
    nonce = nonce or os.urandom(32)
    eph_pub = x25519_pub(eph_priv)
    t1 = b"HL1|hello|" + uuid_bytes(pair_id) + uuid_bytes(client_id) + eph_pub + nonce
    mac = hmac256(hkdf(prk, SESSION_AUTH_INFO, 32), t1)
    data = {"protocol": 1, "pair_id": pair_id, "device_id": client_id, "eph": b64u(eph_pub), "nonce": b64u(nonce),
            "mac": b64u(mac)}
    return HelloKeys(eph_priv, nonce, t1, data)


def session_keys(prk: bytes, hello: HelloKeys, welcome: dict, server_id: str) -> tuple[bytes, bytes] | None:
    """0.6.3 steps 2–3: check the welcome mac and device_id, then (k_c2s, k_s2c); None when invalid."""
    if welcome.get("device_id") != server_id:
        return None
    eph_s, nonce_s = b64u_decode(welcome["eph"], 32), b64u_decode(welcome["nonce"], 32)
    t2 = b"HL1|welcome|" + hello.t1 + uuid_bytes(server_id) + eph_s + nonce_s
    if not hmac.compare_digest(hmac256(hkdf(prk, SESSION_AUTH_INFO, 32), t2), b64u_decode(welcome["mac"], 32)):
        return None
    secret = hkdf(x25519_dh(hello.eph_priv, eph_s) + prk, SESSION_INFO, 64, hashlib.sha256(t2).digest())
    return secret[:32], secret[32:]


def push_key(prk: bytes) -> bytes:
    """0.6.1: K_push = HKDF(PRK, info "handlive/v1/push")."""
    return hkdf(prk, PUSH_INFO, 32)


def plain_envelope(typ: str, op: str, data: dict, env_id: str | None = None, ts: int | None = None) -> dict:
    """Handshake envelopes (0.5.1 exception 1): payload = b64 of the unencrypted JSON."""
    ts = now_ms() if ts is None else ts
    payload = compact_json({"op": op, "data": data}).encode()
    return {"v": 1, "type": typ, "id": env_id or uuid7(ts), "ts": ts, "payload": b64(payload)}


def open_plain(env: dict) -> dict:
    return json.loads(base64.b64decode(env["payload"], validate=True))


def seal(key: bytes, typ: str, plaintext: bytes, env_id: str | None = None, ts: int | None = None,
         nonce: bytes | None = None) -> dict:
    """0.5.1: payload = b64(nonce(24) ‖ ciphertext ‖ tag(16)), AAD = "<v>|<type>|<id>|<ts>"."""
    ts = now_ms() if ts is None else ts
    env_id = env_id or uuid7(ts)
    nonce = nonce or os.urandom(NONCE_LEN)
    ct, tag = xchacha_seal(key, nonce, plaintext, envelope_aad(1, typ, env_id, ts).encode())
    return {"v": 1, "type": typ, "id": env_id, "ts": ts, "payload": b64(nonce + ct + tag)}


def open_sealed(key: bytes, env: dict) -> bytes:
    """Rebuilds the AAD from the parsed values; raises ValueError on a bad tag or a short payload."""
    raw = base64.b64decode(env["payload"], validate=True)
    if len(raw) < NONCE_LEN + TAG_LEN:
        raise ValueError("payload shorter than nonce + tag")
    aad = envelope_aad(env["v"], env["type"], env["id"], env["ts"]).encode()
    try:
        return crypto_aead_xchacha20poly1305_ietf_decrypt(raw[NONCE_LEN:], aad, raw[:NONCE_LEN], key)
    except CryptoError as exc:
        raise ValueError("DECRYPT_FAILED") from exc


def chunk_plaintext(transfer_id: str, index: int, data: bytes) -> bytes:
    """0.5.1: hdr_len (uint16 BE) ‖ JSON {"op":"chunk","data":{transfer_id, index}} ‖ bytes."""
    hdr = compact_json({"op": "chunk", "data": {"transfer_id": transfer_id, "index": index}}).encode()
    return struct.pack(">H", len(hdr)) + hdr + data


def parse_plaintext(raw: bytes) -> tuple[dict, bytes | None]:
    """JSON plaintext, or a binary clipboard chunk (first byte 0x00, CLIP-03 API 4 logic 1)."""
    if raw[:1] == b"\x00":
        (hdr_len,) = struct.unpack(">H", raw[:2])
        return json.loads(raw[2:2 + hdr_len]), raw[2 + hdr_len:]
    return json.loads(raw), None


__all__ = ["Identity", "PairSecrets", "PinOfferCheck", "HelloKeys", "b64", "b64u", "b64u_decode", "build_confirm",
           "check_done", "check_pin_offer", "chunk_plaintext", "compact_json", "ed25519_verify", "new_pin", "now_ms",
           "open_plain", "open_sealed", "parse_plaintext", "plain_envelope", "push_key", "seal", "security_code",
           "session_hello", "session_keys", "uuid7"]
