"""Build revoke.json: the Ed25519 revoke statement of PAIR-03 (relay revocation signed by the revoking device).

message = "HLREVOKE1" ‖ pair_id (16 raw UUID bytes) ‖ by = device_id of the revoking device (16) ‖ revoked_at
(u64 big-endian, ms); sig = Ed25519(ik_sig of the revoking device, message). Keys are RFC 8032 §7.1 TEST 1–3, so
device_id matches device-id.json. Each vector also carries the wire forms: the POST /v1/pairs/{pair_id}/revoke body,
the revocations[] item of DELETE /v1/devices/me?revoke_pairs=true and the relay's pair_revoked frame.

Negative vectors are either for the receiver (a client or the phone holding the pair: `by` must be the peer's
device_id and `sig` must verify with the peer's stored ik_sig_pub) or for the relay (the statement must verify with
the caller's stored key, `by` = JWT subject, revoked_at within ±10 minutes of the relay clock).
The generator signs with `cryptography`; verify_revoke_checks.py checks with libsodium (pynacl).
"""
import rfc_source_values as R
from build_signature_vectors import _s_plus_l
from handlive_protocol_derivations import b64u, compact_json, device_id_from_pub, ed25519_sign, revoke_message

H = bytes.fromhex
SPEC = "docs/detailed-design/00-common-specs.md 0.6, 0.7.3, 0.7.4; 02-pairing.md PAIR-03"
REVOKE_SKEW_MS = 600_000  # relay accepts revoked_at within ±10 minutes of its clock
# Two pairs: macOS (TEST 1) ↔ Android (TEST 2) and iOS (TEST 3) ↔ Android (TEST 2).
PAIR_MAC = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
PAIR_IOS = "7a1e2b3c-4d5e-4f60-9172-83a4b5c6d7e8"
# (name, pair_id, key index of the revoking device, key index of its peer, revoked_at)
CASES = [
    ("macOS revokes its pair with Android (TEST 1)", PAIR_MAC, 0, 1, 1727160000000),
    ("Android revokes its pair with macOS (TEST 2)", PAIR_MAC, 1, 0, 1727160000123),
    ("iOS revokes its pair with Android (TEST 3)", PAIR_IOS, 2, 1, 1727170000456),
]


def _key(index: int) -> tuple[bytes, bytes, str]:
    _name, seed_hex, pub_hex = R.ED25519_8032[index]
    pub = H(pub_hex)
    return H(seed_hex), pub, device_id_from_pub(pub)


def _wire(pair_id: str, by: str, revoked_at: int, sig: bytes) -> dict:
    return {"revoke_request": compact_json({"revoked_at": revoked_at, "sig": b64u(sig)}),
            "revocation": compact_json({"pair_id": pair_id, "revoked_at": revoked_at, "sig": b64u(sig)}),
            "pair_revoked": compact_json({"op": "pair_revoked", "pair_id": pair_id, "by": by,
                                          "revoked_at": revoked_at, "sig": b64u(sig)})}


def _vectors() -> list[dict]:
    out = []
    for name, pair_id, signer, peer, revoked_at in CASES:
        seed, pub, did = _key(signer)
        _pseed, ppub, pdid = _key(peer)
        msg = revoke_message(pair_id, did, revoked_at)
        sig = ed25519_sign(seed, msg)
        out.append({"name": name, "ik_sig_seed": seed.hex(), "ik_sig_pub": pub.hex(), "device_id": did,
                    "pair_id": pair_id, "revoked_at": revoked_at, "message": msg.hex(), "sig": sig.hex(),
                    "sig_b64u": b64u(sig), "peer_device_id": pdid, "peer_ik_sig_pub": ppub.hex(),
                    "relay_now": revoked_at + 1500, **_wire(pair_id, did, revoked_at, sig)})
    return out


def _receiver(name, reason, peer_did, peer_pub, pair_id, by, revoked_at, sig, signed_message=None, signer_pub=None):
    """A pair_revoked frame that a receiver whose stored peer is (peer_did, peer_pub) for pair_id must ignore."""
    v = {"name": name, "check": "receiver", "reason": reason, "pair_id": pair_id, "peer_device_id": peer_did,
         "peer_ik_sig_pub": peer_pub.hex()}
    frame = {"op": "pair_revoked", "pair_id": pair_id, "by": by}
    if revoked_at is not None:
        frame["revoked_at"] = revoked_at
    if sig is not None:
        frame["sig"] = b64u(sig)
    v["pair_revoked"] = compact_json(frame)
    if signed_message is not None:
        v["signed_message"] = signed_message.hex()
    if signer_pub is not None:
        v["signer_pub"] = signer_pub.hex()
    return v


def _relay(name, reason, caller_did, caller_pub, pair_id, relay_now, body, signed_message=None, signer_pub=None):
    """A POST /v1/pairs/{pair_id}/revoke body the relay must refuse with 400 BAD_REQUEST."""
    v = {"name": name, "check": "relay", "reason": reason, "pair_id": pair_id, "caller_device_id": caller_did,
         "caller_ik_sig_pub": caller_pub.hex(), "relay_now": relay_now, "revoke_request": compact_json(body)}
    if signed_message is not None:
        v["signed_message"] = signed_message.hex()
    if signer_pub is not None:
        v["signer_pub"] = signer_pub.hex()
    return v


def _negatives() -> list[dict]:
    s1, p1, d1 = _key(0)  # macOS
    s2, p2, d2 = _key(1)  # Android
    s3, p3, d3 = _key(2)  # iOS, a third device that is not a member of PAIR_MAC
    t = 1727160000000
    neg = []
    # Receiver = Android holding PAIR_MAC with the Mac as its peer.
    m = revoke_message(PAIR_MAC, d3, t)
    neg.append(_receiver("pair_revoked / by is not the peer (third device signs for itself)", "by_not_peer",
                         d1, p1, PAIR_MAC, d3, t, ed25519_sign(s3, m), m, p3))
    m = revoke_message(PAIR_MAC, d1, t)
    neg.append(_receiver("pair_revoked / third device signs in the peer's name", "wrong_key",
                         d1, p1, PAIR_MAC, d1, t, ed25519_sign(s3, m), m, p3))
    sig = ed25519_sign(s1, m)
    neg.append(_receiver("pair_revoked / revoked_at changed after signing", "message_tampered",
                         d1, p1, PAIR_MAC, d1, t + 1, sig, m))
    m_other = revoke_message(PAIR_IOS, d1, t)
    neg.append(_receiver("pair_revoked / statement of another pair replayed", "message_tampered",
                         d1, p1, PAIR_MAC, d1, t, ed25519_sign(s1, m_other), m_other))
    m_label = b"HLAUTH1" + m[9:]
    neg.append(_receiver("pair_revoked / signed with label HLAUTH1", "wrong_label",
                         d1, p1, PAIR_MAC, d1, t, ed25519_sign(s1, m_label), m_label))
    neg.append(_receiver("pair_revoked / S + L (not canonical)", "signature_not_canonical",
                         d1, p1, PAIR_MAC, d1, t, _s_plus_l(sig), m))
    neg.append(_receiver("pair_revoked / no statement (row revoked before signed revocation)", "missing_statement",
                         d1, p1, PAIR_MAC, d1, None, None))
    # Relay: the Mac calls POST /v1/pairs/PAIR_MAC/revoke with its JWT.
    neg.append(_relay("revoke / revoked_at 10 min + 1 ms before the relay clock", "stale",
                      d1, p1, PAIR_MAC, t + REVOKE_SKEW_MS + 1, {"revoked_at": t, "sig": b64u(sig)}, m))
    neg.append(_relay("revoke / revoked_at 10 min + 1 ms after the relay clock", "stale",
                      d1, p1, PAIR_MAC, t - REVOKE_SKEW_MS - 1, {"revoked_at": t, "sig": b64u(sig)}, m))
    m2 = revoke_message(PAIR_MAC, d2, t)
    neg.append(_relay("revoke / statement names the peer instead of the caller", "by_not_caller",
                      d1, p1, PAIR_MAC, t, {"revoked_at": t, "sig": b64u(ed25519_sign(s2, m2))}, m2, p2))
    neg.append(_relay("revoke / revoked_at changed after signing", "message_tampered",
                      d1, p1, PAIR_MAC, t, {"revoked_at": t + 1, "sig": b64u(sig)}, m))
    neg.append(_relay("revoke / sig 63 bytes", "signature_length",
                      d1, p1, PAIR_MAC, t, {"revoked_at": t, "sig": b64u(sig[:63])}))
    neg.append(_relay("revoke / no sig", "missing_statement", d1, p1, PAIR_MAC, t, {"revoked_at": t}))
    return neg


def revoke_file() -> dict:
    return {"description": "Revoke statement (PAIR-03): message = \"HLREVOKE1\" ‖ pair_id (16 raw UUID bytes) ‖ by = "
                           "device_id of the revoking device (16 raw bytes, 0.2) ‖ revoked_at (u64 big-endian, ms); "
                           "sig = Ed25519(ik_sig of the revoking device, message), 64 bytes, b64u on the wire. "
                           "revoke_request = body of POST /v1/pairs/{pair_id}/revoke; revocation = one item of "
                           "revocations[] in DELETE /v1/devices/me?revoke_pairs=true; pair_revoked = the relay frame "
                           "forwarded to the peer. The relay accepts a statement when sig verifies with the caller's "
                           "stored ik_sig_pub, by = the JWT subject and |relay_now − revoked_at| ≤ 600,000 ms, else "
                           "400 BAD_REQUEST. A receiver acts on pair_revoked only when by = peer_device_id of that pair "
                           "and sig verifies with peer_ik_sig_pub (strict: S < L); otherwise it ignores the frame. "
                           "Every invalid_vectors entry must be refused by the side named in check, for its reason.",
            "source": f"{SPEC}; keys from RFC 8032 §7.1 TEST 1–3 (device-id.json)",
            "vectors": _vectors(), "invalid_vectors": _negatives()}


def build() -> dict:
    return {"revoke.json": revoke_file()}
