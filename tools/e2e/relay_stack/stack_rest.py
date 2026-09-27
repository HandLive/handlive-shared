"""A small client of the relay REST API for the checks, and fake devices that go through CONN-03 as the apps do:
`POST /v1/devices` signed with HLREG1, challenge → HLAUTH1 → JWT, `POST /v1/pairs` with the 0.6.2 attestation signed by
both devices. The signed messages come from tools/vectors/handlive_protocol_derivations.py (the code behind
test-vectors/relay-auth.json). TLS is verified against the stack's CA.
"""
from __future__ import annotations

import base64
import json
import secrets
import ssl
import struct
import time
import urllib.error
import urllib.request
import uuid
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vectors"))
from handlive_protocol_derivations import (auth_message, b64u, device_id_from_pub, ed25519_pub,  # noqa: E402
                                           ed25519_sign, registration_message, uuid_bytes)

APP_VERSION = "0.0.0 (e2e)"  # tells the fake devices apart from the real apps in the relay's database


class RelayRest:
    def __init__(self, base: str, ca_file: str | None, timeout_s: float = 15) -> None:
        self.base, self.timeout_s = base.rstrip("/"), timeout_s
        self.ctx = ssl.create_default_context(cafile=ca_file) if base.startswith("https") else None

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None,
             xff: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", "User-Agent": "handlive-relay-stack-check"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if xff:
            headers["X-Forwarded-For"] = xff
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s, context=self.ctx) as response:
                text = response.read()
                return response.status, json.loads(text) if text else {}
        except urllib.error.HTTPError as error:
            text = error.read()
            try:
                return error.code, json.loads(text) if text else {}
            except ValueError:
                return error.code, {}


def error_code(reply: dict) -> str:
    return (reply.get("error") or {}).get("code", "")


@dataclass
class FakeDevice:
    platform: str
    seed: bytes
    token: str = ""

    @classmethod
    def new(cls, platform: str) -> "FakeDevice":
        return cls(platform, secrets.token_bytes(32))

    @property
    def pub(self) -> bytes:
        return ed25519_pub(self.seed)

    @property
    def device_id(self) -> str:
        return device_id_from_pub(self.pub)

    def register(self, rest: RelayRest, xff: str) -> tuple[int, dict]:
        """CONN-03 API 1–3; keeps the JWT. Returns the first failing (status, body), or (200, {})."""
        ts = int(time.time() * 1000)
        sig = ed25519_sign(self.seed, registration_message(self.device_id, self.pub, self.platform, ts))
        status, reply = rest.call("POST", "/v1/devices", {
            "device_id": self.device_id, "platform": self.platform, "app_version": APP_VERSION,
            "ik_sig_pub": b64u(self.pub), "ts": ts, "sig": b64u(sig)}, xff=xff)
        if status not in (200, 201):
            return status, reply
        status, reply = rest.call("POST", "/v1/auth/challenge", {"device_id": self.device_id}, xff=xff)
        if status != 200:
            return status, reply
        challenge = base64.urlsafe_b64decode(reply["challenge"] + "=" * (-len(reply["challenge"]) % 4))
        status, reply = rest.call("POST", "/v1/auth/token", {
            "device_id": self.device_id, "challenge": reply["challenge"],
            "sig": b64u(ed25519_sign(self.seed, auth_message(challenge, self.device_id)))}, xff=xff)
        if status != 200:
            return status, reply
        self.token = reply["access_token"]
        return 200, {}


def register_pair(rest: RelayRest, phone: FakeDevice, client: FakeDevice) -> tuple[int, dict, str]:
    """PAIR-01 API 8 by the phone: (status, body, pair_id)."""
    pair_id, created_at = str(uuid.uuid4()), int(time.time() * 1000)
    attestation = (b"HLPAIR1" + uuid_bytes(pair_id) + uuid_bytes(phone.device_id) + uuid_bytes(client.device_id)
                   + phone.pub + client.pub + struct.pack(">q", created_at))
    status, reply = rest.call("POST", "/v1/pairs", {
        "pair_id": pair_id, "device_a": phone.device_id, "device_b": client.device_id, "created_at": created_at,
        "attestation": b64u(attestation), "sig_a": b64u(ed25519_sign(phone.seed, attestation)),
        "sig_b": b64u(ed25519_sign(client.seed, attestation))}, token=phone.token)
    return status, reply, pair_id


def fake_xff() -> str:
    """A random private address per fake device, sent as X-Forwarded-For: the relay's limit of 10 new registrations
    per hour and IP then applies to it rather than to 127.0.0.1 (the TLS front appends its own peer address)."""
    return f"10.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{secrets.randbelow(254) + 1}"
