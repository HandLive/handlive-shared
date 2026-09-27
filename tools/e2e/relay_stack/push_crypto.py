"""Push envelopes (0.4.4, CONN-04 step 5b): K_push = HKDF-SHA256(PRK, empty salt, "handlive/v1/push", 32); the
envelope is sealed as over a session (0.5.1: 24-byte nonce ‖ ciphertext ‖ tag, AAD "<v>|<type>|<id>|<ts>") and
`env_b64` / APNs `hl` is standard base64 of the envelope JSON.

`open_hl` is what an iPhone's Notification Service Extension does with a captured `hl`; `summary` keeps only what a
report may show: the envelope type and op, the call state or SMS key — never numbers, names or message text.
"""
from __future__ import annotations

import base64
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vectors"))
from handlive_protocol_derivations import (b64, compact_json, envelope_aad, envelope_wire, hkdf,  # noqa: E402
                                           xchacha_seal)

PUSH_INFO = b"handlive/v1/push"


def push_key(prk: bytes) -> bytes:
    return hkdf(prk, PUSH_INFO, 32)


def uuid7(ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if ms is None else ms
    raw = bytearray(ms.to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def seal(k_push: bytes, typ: str, plaintext: dict, env_id: str | None = None, ts: int | None = None) -> str:
    """env_b64 of a push envelope carrying `plaintext`."""
    ts = int(time.time() * 1000) if ts is None else ts
    env_id = env_id or uuid7(ts)
    nonce = secrets.token_bytes(24)
    ct, tag = xchacha_seal(k_push, nonce, compact_json(plaintext).encode(), envelope_aad(1, typ, env_id, ts).encode())
    return b64(envelope_wire(1, typ, env_id, ts, b64(nonce + ct + tag)).encode())


def open_hl(k_push: bytes, hl: str) -> tuple[dict, dict]:
    """(envelope without payload, decrypted payload) of a captured `hl`; raises ValueError when it does not open."""
    envelope = json.loads(base64.b64decode(hl, validate=True))
    sealed = base64.b64decode(envelope["payload"], validate=True)
    aad = envelope_aad(envelope["v"], envelope["type"], envelope["id"], envelope["ts"]).encode()
    try:
        plain = crypto_aead_xchacha20poly1305_ietf_decrypt(sealed[24:], aad, sealed[:24], k_push)
    except Exception as error:  # nacl raises CryptoError
        raise ValueError(f"hl does not open with this K_push: {type(error).__name__}") from error
    head = {k: v for k, v in envelope.items() if k != "payload"}
    return head, json.loads(plain)


def summary(head: dict, payload: dict) -> dict:
    """What may be printed: type, op and the non-personal fields of the payload."""
    data = payload.get("data") or {}
    out = {"type": head.get("type"), "id": head.get("id"), "ts": head.get("ts"), "op": payload.get("op")}
    if head.get("type") == "call_event":
        if payload.get("op") == "state":
            out.update({k: data.get(k) for k in ("call_id", "direction", "state", "presentation", "end_reason")})
            out["has_number"] = data.get("number") is not None
        elif payload.get("op") == "log_new":
            entry = data.get("entry") or {}
            out.update({"call_id": data.get("call_id"), "entry_type": entry.get("type")})
            out["has_number"] = entry.get("number") is not None
    elif head.get("type") == "sms":
        message = data.get("message") or {}
        out.update({"message_key": message.get("message_key"), "box": message.get("box"),
                    "body_chars": len(message.get("body") or "")})
    return out


def fake_call_ringing(number: str = "+15555550100") -> tuple[str, dict]:
    """(call_id, call_event/state ringing) as CALL-01 API 4 sends to an iPhone, with a fake number."""
    call_id, now = uuid7(), int(time.time() * 1000)
    controls = {"answer": False, "reject": True, "end": False, "hold": "unavailable", "dtmf": "unavailable",
                "mute": "unavailable"}
    data = {"call_id": call_id, "direction": "incoming", "state": "ringing", "waiting": False, "number": number,
            "display_name": None, "presentation": "allowed", "sub_id": None, "sim_label": None,
            "waiting_number": None, "waiting_display_name": None, "started_at": now, "answered_at": None,
            "ended_at": None, "end_reason": None, "controls": controls, "hfp_connected": False, "audio_on": "phone"}
    return call_id, {"op": "state", "data": data}


def fake_call_missed(call_id: str, number: str = "+15555550100") -> dict:
    """call_event/log_new of a missed call (CALL-04 API 5) matched with `call_id`."""
    now = int(time.time() * 1000)
    return {"op": "log_new", "data": {"entry": {"entry_id": 1, "number": number, "display_name": None,
                                                "type": "missed", "ts": now, "duration_s": 0, "sub_id": None},
                                      "call_id": call_id}}


def fake_sms_new(message_id: int = 1, number: str = "+15555550101") -> dict:
    """sms/new (SMS-02 API 2) of a short test message from a fake number."""
    now = int(time.time() * 1000)
    body = "E2E relay push test"
    return {"op": "new", "data": {
        "message": {"message_key": f"sms:{message_id}", "thread_id": 1, "address": number, "body": body,
                    "box": "inbox", "ts": now, "ts_sent": None, "read": False, "sub_id": None},
        "thread": {"thread_id": 1, "addresses": [number], "display_name": None, "snippet": body, "last_ts": now,
                   "unread_count": 1}}}
