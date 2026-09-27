"""A minimal in-process stand-in for the relay, to test relay_load.py without PostgreSQL, Redis or the Rust server.

It checks what the load test sends the way the relay does (HLREG1 and HLAUTH1 signatures, device_id derived from
the key, both attestation signatures, the bearer token, 10 registrations per hour per client IP taken from
X-Forwarded-For) and forwards like 0.4.3: {"to", "env"} → {"from", "env"}, HR frames with the destination swapped
for the source, presence on connect, relay error ops NOT_PAIRED / NOT_CONNECTED / BAD_REQUEST. Signatures are
verified with libsodium (pynacl), apart from the `cryptography` signer of the load test.

REST runs on one port (asyncio streams, HTTP/1.1 with Content-Length), /v1/relay on another (websockets).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import struct
import time
import uuid

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

REGISTRATIONS_PER_IP = 10


def _b64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _device_id(pub: bytes) -> str:
    raw = bytearray(hashlib.sha256(pub).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x80
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _verify(pub: bytes, message: bytes, sig: bytes) -> bool:
    try:
        VerifyKey(pub).verify(message, sig)
        return True
    except (BadSignatureError, ValueError):
        return False


class FakeRelay:
    def __init__(self) -> None:
        self.devices: dict[str, dict] = {}
        self.challenges: dict[str, bytes] = {}
        self.tokens: dict[str, str] = {}
        self.pairs: dict[str, tuple[str, str]] = {}
        self.per_ip: dict[str, int] = {}
        self.sockets: dict[str, object] = {}
        self.rest_port = self.ws_port = 0

    # REST ---------------------------------------------------------------------------------------------------------
    async def start(self) -> None:
        self.rest = await asyncio.start_server(self._http, "127.0.0.1", 0)
        self.rest_port = self.rest.sockets[0].getsockname()[1]
        self.ws = await serve(self._relay, "127.0.0.1", 0, process_request=self._upgrade)
        self.ws_port = list(self.ws.sockets)[0].getsockname()[1]

    async def stop(self) -> None:
        self.rest.close()
        self.ws.close()
        await self.rest.wait_closed()
        await self.ws.wait_closed()

    async def _http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode().split("\r\n")
                method, target, _ = lines[0].split(" ", 2)
                headers = {k.lower(): v.strip() for k, v in (h.split(":", 1) for h in lines[1:] if ":" in h)}
                body = await reader.readexactly(int(headers.get("content-length", "0")))
                ip = headers.get("x-forwarded-for", writer.get_extra_info("peername")[0])
                status, reply = self._route(method, target, headers, json.loads(body) if body else None, ip)
                data = json.dumps(reply).encode() if reply is not None else b""
                writer.write(f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(data)}"
                             f"\r\nConnection: close\r\n\r\n".encode() + data)
                await writer.drain()
                break
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    def _auth(self, headers: dict) -> str | None:
        value = headers.get("authorization", "")
        return self.tokens.get(value[7:]) if value.startswith("Bearer ") else None

    def _route(self, method: str, target: str, headers: dict, body, ip: str) -> tuple[int, dict | None]:
        err = lambda status, code: (status, {"error": {"code": code, "message": code}})  # noqa: E731
        if (method, target) == ("POST", "/v1/devices"):
            pub = _b64u(body["ik_sig_pub"])
            msg = (b"HLREG1" + uuid.UUID(body["device_id"]).bytes + pub + body["platform"].encode()
                   + struct.pack(">q", body["ts"]))
            if _device_id(pub) != body["device_id"] or not _verify(pub, msg, _b64u(body["sig"])):
                return err(401, "SIGNATURE_INVALID")
            if body["device_id"] not in self.devices:
                self.per_ip[ip] = self.per_ip.get(ip, 0) + 1
                if self.per_ip[ip] > REGISTRATIONS_PER_IP:
                    return err(429, "RATE_LIMITED")
            self.devices[body["device_id"]] = {"pub": pub, "platform": body["platform"]}
            return 201, {"device_id": body["device_id"], "created_at": int(time.time() * 1000)}
        if (method, target) == ("POST", "/v1/auth/challenge"):
            if body["device_id"] not in self.devices:
                return err(404, "DEVICE_NOT_FOUND")
            self.challenges[body["device_id"]] = secrets.token_bytes(32)
            challenge = base64.urlsafe_b64encode(self.challenges[body["device_id"]]).decode().rstrip("=")
            return 200, {"challenge": challenge, "expires_at": int(time.time() * 1000) + 60_000}
        if (method, target) == ("POST", "/v1/auth/token"):
            challenge = self.challenges.pop(body["device_id"], None)
            if challenge is None or _b64u(body["challenge"]) != challenge:
                return err(401, "CHALLENGE_EXPIRED")
            msg = b"HLAUTH1" + challenge + uuid.UUID(body["device_id"]).bytes
            if not _verify(self.devices[body["device_id"]]["pub"], msg, _b64u(body["sig"])):
                return err(401, "SIGNATURE_INVALID")
            token = ".".join(secrets.token_urlsafe(12) for _ in range(3))
            self.tokens[token] = body["device_id"]
            return 200, {"access_token": token, "expires_in": 900}
        caller = self._auth(headers)
        if caller is None:
            return err(401, "SIGNATURE_INVALID")
        if (method, target) == ("POST", "/v1/pairs"):
            a, b = body["device_a"], body["device_b"]
            att = _b64u(body["attestation"])
            want = (b"HLPAIR1" + uuid.UUID(body["pair_id"]).bytes + uuid.UUID(a).bytes + uuid.UUID(b).bytes
                    + self.devices[a]["pub"] + self.devices[b]["pub"] + struct.pack(">q", body["created_at"]))
            if caller not in (a, b):
                return err(403, "NOT_PAIRED")
            if att != want or not (_verify(self.devices[a]["pub"], att, _b64u(body["sig_a"]))
                                   and _verify(self.devices[b]["pub"], att, _b64u(body["sig_b"]))):
                return err(401, "SIGNATURE_INVALID")
            self.pairs[body["pair_id"]] = (a, b)
            return 201, {"pair_id": body["pair_id"], "created_at": body["created_at"]}
        if method == "DELETE" and target.startswith("/v1/devices/me"):
            self.devices.pop(caller, None)
            return 204, None
        return err(404, "DEVICE_NOT_FOUND")

    # /v1/relay ----------------------------------------------------------------------------------------------------
    def _upgrade(self, connection, request):
        device = self._auth({"authorization": request.headers.get("Authorization", "")})
        if request.path != "/v1/relay" or device is None:
            return Response(401, "Unauthorized", Headers(), b"")
        connection.device_id = device
        return None

    def _peers(self, device: str) -> list[tuple[str, str]]:
        return [(pid, b if a == device else a) for pid, (a, b) in self.pairs.items() if device in (a, b)]

    async def _relay(self, ws) -> None:
        me = ws.device_id
        self.sockets[me] = ws
        for pair_id, peer in self._peers(me):
            await ws.send(json.dumps({"op": "presence", "pair_id": pair_id, "peer_device_id": peer,
                                      "online": peer in self.sockets}))
            if peer in self.sockets:
                await self.sockets[peer].send(json.dumps({"op": "presence", "pair_id": pair_id,
                                                          "peer_device_id": me, "online": True}))
        try:
            async for message in ws:
                await self._forward(me, ws, message)
        finally:
            self.sockets.pop(me, None)

    async def _forward(self, me: str, ws, message) -> None:
        peers = {peer for _, peer in self._peers(me)}
        if isinstance(message, bytes):
            if len(message) <= 20 or message[:4] != b"HR\x01\x01":
                return await ws.send(json.dumps({"op": "error", "code": "BAD_REQUEST", "message": "bad frame"}))
            to = str(uuid.UUID(bytes=message[4:20]))
            out = message[:4] + uuid.UUID(me).bytes + message[20:]
        else:
            frame = json.loads(message)
            to = frame.get("to")
            if to is None or "env" not in frame:
                return await ws.send(json.dumps({"op": "error", "code": "BAD_REQUEST", "message": "bad wrapper"}))
            out = json.dumps({"from": me, "env": frame["env"]}, separators=(",", ":"))
        if to not in peers:
            return await ws.send(json.dumps({"op": "error", "code": "NOT_PAIRED", "message": "not paired", "to": to}))
        target = self.sockets.get(to)
        if target is None:
            return await ws.send(json.dumps({"op": "error", "code": "NOT_CONNECTED", "message": "offline", "to": to}))
        await target.send(out)
