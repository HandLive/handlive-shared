"""Check revoke.json with libsodium (pynacl), independent of the generator (`cryptography`).

The message is rebuilt from the JSON fields with `struct`/`uuid16`; the relay's and the receiver's decisions are
reimplemented here, and each negative vector must be refused by the side named in `check` for its stated `reason`.
"""
import json
import struct

from nacl.signing import SigningKey

from verify_common import H, b64u, b64u_decode, uuid16
from verify_session_checks import device_id
from verify_signature_checks import L, _reduced, verifies

SKEW_MS = 600_000
REQUEST_FIELDS = ["revoked_at", "sig"]
REVOCATION_FIELDS = ["pair_id", "revoked_at", "sig"]
FRAME_FIELDS = ["op", "pair_id", "by", "revoked_at", "sig"]


def message(pair_id: str, by: str, revoked_at: int) -> bytes:
    return b"HLREVOKE1" + uuid16(pair_id) + uuid16(by) + struct.pack(">Q", revoked_at)


def _compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def relay_decision(caller_did: str, caller_pub: bytes, pair_id: str, relay_now: int, body: dict) -> str | None:
    """The relay's checks of POST /v1/pairs/{pair_id}/revoke: the refusal reason, None when accepted."""
    if not isinstance(body.get("revoked_at"), int) or "sig" not in body:
        return "missing_statement"
    sig = b64u_decode(body["sig"])
    if len(sig) != 64:
        return "signature_length"
    if abs(relay_now - body["revoked_at"]) > SKEW_MS:
        return "stale"
    # by is always the JWT subject: the relay never takes it from the body.
    return None if verifies(caller_pub, message(pair_id, caller_did, body["revoked_at"]), sig) else "signature_invalid"


def receiver_decision(pair_id: str, peer_did: str, peer_pub: bytes, frame: dict) -> str | None:
    """A client's or the phone's checks of pair_revoked: the reason it ignores the frame, None when it acts on it."""
    if frame.get("pair_id") != pair_id:
        return "unknown_pair"
    if "sig" not in frame or "revoked_at" not in frame:
        return "missing_statement"
    if frame["by"] != peer_did:
        return "by_not_peer"
    sig = b64u_decode(frame["sig"])
    return None if verifies(peer_pub, message(pair_id, frame["by"], frame["revoked_at"]), sig) else "signature_invalid"


def check_revoke(c, doc, all_docs):
    ids = {v["ik_sig_pub"]: v["device_id"] for v in all_docs["device-id.json"]["vectors"]}
    for v in doc["vectors"]:
        n = f"revoke/{v['name']}"
        seed, pub, did = H(v["ik_sig_seed"]), H(v["ik_sig_pub"]), v["device_id"]
        key = SigningKey(seed)
        c.eq(f"{n} ik_sig_pub from seed", bytes(key.verify_key), pub)
        c.eq(f"{n} device_id from key", device_id(pub), did)
        c.eq(f"{n} device_id matches device-id.json", ids.get(v["ik_sig_pub"]), did)
        c.eq(f"{n} peer device_id matches device-id.json", ids.get(v["peer_ik_sig_pub"]), v["peer_device_id"])
        c.true(f"{n} peer is another device", v["peer_device_id"] != did)
        msg = message(v["pair_id"], did, v["revoked_at"])
        c.eq(f"{n} message", msg.hex(), v["message"])
        c.eq(f"{n} message 49 bytes", len(msg), 9 + 16 + 16 + 8)
        c.eq(f"{n} deterministic signature", key.sign(msg).signature.hex(), v["sig"])
        c.true(f"{n} signature valid", verifies(pub, msg, H(v["sig"])))
        c.eq(f"{n} sig_b64u", b64u(H(v["sig"])), v["sig_b64u"])
        req = json.loads(v["revoke_request"])
        c.eq(f"{n} revoke_request fields", list(req), REQUEST_FIELDS)
        c.eq(f"{n} revoke_request compact", _compact(req), v["revoke_request"])
        c.eq(f"{n} revoke_request values", (req["revoked_at"], req["sig"]), (v["revoked_at"], v["sig_b64u"]))
        item = json.loads(v["revocation"])
        c.eq(f"{n} revocation fields", list(item), REVOCATION_FIELDS)
        c.eq(f"{n} revocation values", (item["pair_id"], item["revoked_at"], item["sig"]),
             (v["pair_id"], v["revoked_at"], v["sig_b64u"]))
        frame = json.loads(v["pair_revoked"])
        c.eq(f"{n} pair_revoked fields", list(frame), FRAME_FIELDS)
        c.eq(f"{n} pair_revoked values", (frame["op"], frame["pair_id"], frame["by"], frame["revoked_at"], frame["sig"]),
             ("pair_revoked", v["pair_id"], did, v["revoked_at"], v["sig_b64u"]))
        c.eq(f"{n} relay accepts", relay_decision(did, pub, v["pair_id"], v["relay_now"], req), None)
        c.eq(f"{n} peer acts on pair_revoked",
             receiver_decision(v["pair_id"], did, pub, frame), None)
    reasons = set()
    for v in doc["invalid_vectors"]:
        n = f"revoke/{v['name']}"
        reason, check = v["reason"], v["check"]
        reasons.add((check, reason))
        if check == "relay":
            body = json.loads(v["revoke_request"])
            decision = relay_decision(v["caller_device_id"], H(v["caller_ik_sig_pub"]), v["pair_id"], v["relay_now"],
                                      body)
            sig = b64u_decode(body["sig"]) if "sig" in body else b""
            pub = H(v["caller_ik_sig_pub"])
        else:
            frame = json.loads(v["pair_revoked"])
            decision = receiver_decision(v["pair_id"], v["peer_device_id"], H(v["peer_ik_sig_pub"]), frame)
            sig = b64u_decode(frame["sig"]) if "sig" in frame else b""
            pub = H(v.get("signer_pub", v["peer_ik_sig_pub"]))
        c.true(f"{n} must be refused", decision is not None)
        if reason in ("missing_statement", "stale", "signature_length", "by_not_peer"):
            c.eq(f"{n} refused for {reason}", decision, reason)
        else:
            c.eq(f"{n} refused by the signature", decision, "signature_invalid")
        if "signed_message" in v:
            c.true(f"{n} sig valid for the message actually signed", verifies(
                H(v["signer_pub"]) if "signer_pub" in v else pub, H(v["signed_message"]),
                _reduced(sig) if reason == "signature_not_canonical" else sig))
        if reason == "by_not_peer":
            c.true(f"{n} signer is a real third device", device_id(H(v["signer_pub"])) == frame["by"])
        elif reason == "wrong_key":
            c.true(f"{n} signer is not the peer", v["signer_pub"] != v["peer_ik_sig_pub"])
        elif reason == "by_not_caller":
            c.true(f"{n} statement names another device",
                   H(v["signed_message"])[25:41] != uuid16(v["caller_device_id"]))
        elif reason == "wrong_label":
            c.true(f"{n} signed message carries another label", not H(v["signed_message"]).startswith(b"HLREVOKE1"))
        elif reason == "signature_not_canonical":
            c.true(f"{n} S ≥ L", int.from_bytes(sig[32:], "little") >= L)
        elif reason == "stale":
            c.true(f"{n} just outside ±10 min", abs(v["relay_now"] - body["revoked_at"]) == SKEW_MS + 1)
    c.eq("revoke: every negative kind covered", reasons,
         {("receiver", r) for r in ("by_not_peer", "wrong_key", "message_tampered", "wrong_label",
                                    "signature_not_canonical", "missing_statement")}
         | {("relay", r) for r in ("stale", "by_not_caller", "message_tampered", "signature_length",
                                   "missing_statement")})


CHECKS = {"revoke.json": check_revoke}
