"""Relay load test: N fake devices register, authenticate, pair up, open /v1/relay and forward frames to their peer.

    tools/.venv/bin/python tools/bench/relay_load.py --relay http://127.0.0.1:8080 [--devices 1000] [--frames 10]
        [--interval-ms 1000] [--payload-bytes 200] [--binary] [--no-xff] [--cleanup] [--json]

Every device has its own Ed25519 identity (device_id = UUIDv8 of the key, 0.2) and goes through CONN-03 exactly as
an app: POST /v1/devices (HLREG1), POST /v1/auth/challenge and /v1/auth/token (HLAUTH1) — the signed messages come
from tools/vectors/handlive_protocol_derivations.py, the code that builds test-vectors/relay-auth.json. Devices 2k
(android) and 2k+1 (macos or ios) register their pair (POST /v1/pairs, the 0.6.2 attestation signed by both). Then
every device opens /v1/relay; once all are connected, each sends --frames envelopes to its peer, one every
--interval-ms: text wrappers {"to", "env"}, alternating with binary HR frames when --binary is set. The receiving
side of the same process timestamps each frame, so the forwarding latency needs no clock sync.

Report: failures per step (HTTP status and error code, WebSocket close codes, relay error ops), frames lost, and the
p50, p95, p99 and maximum of the registration, connection and forwarding times. --check exits 1 on any failure or
lost frame.

The relay allows 10 new registrations per hour per IP (CONN-03 API 1). Run it with RELAY_TRUSTED_PROXIES=127.0.0.1
so that the X-Forwarded-For this script sends (one 10.x.y.z address per device) counts, or pass --no-xff with at
most 10 devices. Each connection needs a file descriptor on both sides: raise `ulimit -n` for the relay; this script
raises its own soft limit.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import resource
import secrets
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vectors"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_log import percentile  # noqa: E402
from handlive_protocol_derivations import (auth_message, b64u, device_id_from_pub, ed25519_pub,  # noqa: E402
                                           ed25519_sign, registration_message, uuid_bytes)
from websockets.asyncio.client import connect  # noqa: E402
from websockets.exceptions import ConnectionClosed, InvalidStatus  # noqa: E402

APP_VERSION = "0.0.0 (load)"
CLIENT_PLATFORMS = ("macos", "ios")


@dataclass
class Device:
    index: int
    seed: bytes
    platform: str
    pub: bytes = b""
    device_id: str = ""
    token: str = ""
    peer: str = ""
    ws: object = None
    presence: int = 0
    closed: str = ""

    def __post_init__(self) -> None:
        self.pub = ed25519_pub(self.seed)
        self.device_id = device_id_from_pub(self.pub)

    @property
    def ip(self) -> str:
        return f"10.{(self.index >> 16) & 255}.{(self.index >> 8) & 255}.{self.index & 255}"


@dataclass
class Stats:
    failures: dict[str, int] = field(default_factory=dict)  # "step: status/code" → count
    relay_errors: dict[str, int] = field(default_factory=dict)  # relay error op code → count
    closes: dict[str, int] = field(default_factory=dict)  # unexpected close code → count
    register_ms: list[float] = field(default_factory=list)
    connect_ms: list[float] = field(default_factory=list)
    latency_ms: dict[str, list[float]] = field(default_factory=lambda: {"text": [], "binary": []})
    sent: dict[str, int] = field(default_factory=lambda: {"text": 0, "binary": 0})
    pending: dict[tuple, float] = field(default_factory=dict)  # (receiver, kind, key) → send time
    connected: int = 0
    pairs: int = 0

    def fail(self, step: str, detail: str) -> None:
        key = f"{step}: {detail}"
        self.failures[key] = self.failures.get(key, 0) + 1


class Relay:
    """REST calls through urllib in worker threads (standard library), at most `limit` at a time."""

    def __init__(self, base: str, limit: int, xff: bool, timeout_s: float) -> None:
        self.base, self.xff, self.timeout_s = base.rstrip("/"), xff, timeout_s
        self.gate = asyncio.Semaphore(limit)

    async def call(self, method: str, path: str, body: dict | None, device: Device | None = None,
                   token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self.xff and device is not None:
            headers["X-Forwarded-For"] = device.ip
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        async with self.gate:
            return await asyncio.to_thread(self._send, request)

    def _send(self, request: urllib.request.Request) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                text = response.read()
                return response.status, json.loads(text) if text else {}
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {}
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            return 0, {"error": {"code": type(error).__name__}}


def _code(status: int, body: dict) -> str:
    return f"{status} {body.get('error', {}).get('code', '')}".strip()


async def register(relay: Relay, device: Device, stats: Stats) -> bool:
    start = time.perf_counter()
    ts = int(time.time() * 1000)
    body = {"device_id": device.device_id, "platform": device.platform, "app_version": APP_VERSION,
            "ik_sig_pub": b64u(device.pub), "ts": ts,
            "sig": b64u(ed25519_sign(device.seed, registration_message(device.device_id, device.pub,
                                                                       device.platform, ts)))}
    status, reply = await relay.call("POST", "/v1/devices", body, device)
    if status not in (200, 201):
        stats.fail("POST /v1/devices", _code(status, reply))
        return False
    status, reply = await relay.call("POST", "/v1/auth/challenge", {"device_id": device.device_id}, device)
    if status != 200:
        stats.fail("POST /v1/auth/challenge", _code(status, reply))
        return False
    challenge = base64.urlsafe_b64decode(reply["challenge"] + "=" * (-len(reply["challenge"]) % 4))
    body = {"device_id": device.device_id, "challenge": reply["challenge"],
            "sig": b64u(ed25519_sign(device.seed, auth_message(challenge, device.device_id)))}
    status, reply = await relay.call("POST", "/v1/auth/token", body, device)
    if status != 200:
        stats.fail("POST /v1/auth/token", _code(status, reply))
        return False
    device.token = reply["access_token"]
    stats.register_ms.append((time.perf_counter() - start) * 1000)
    return True


async def pair_up(relay: Relay, phone: Device, client: Device, stats: Stats) -> bool:
    pair_id, created_at = str(uuid.uuid4()), int(time.time() * 1000)
    attestation = (b"HLPAIR1" + uuid_bytes(pair_id) + uuid_bytes(phone.device_id) + uuid_bytes(client.device_id)
                   + phone.pub + client.pub + struct.pack(">q", created_at))
    body = {"pair_id": pair_id, "device_a": phone.device_id, "device_b": client.device_id,
            "created_at": created_at, "attestation": b64u(attestation),
            "sig_a": b64u(ed25519_sign(phone.seed, attestation)), "sig_b": b64u(ed25519_sign(client.seed, attestation))}
    status, reply = await relay.call("POST", "/v1/pairs", body, phone, phone.token)
    if status not in (200, 201):
        stats.fail("POST /v1/pairs", _code(status, reply))
        return False
    phone.peer, client.peer = client.device_id, phone.device_id
    stats.pairs += 1
    return True


async def open_socket(ws_url: str, device: Device, stats: Stats, gate: asyncio.Semaphore, timeout_s: float) -> None:
    async with gate:
        start = time.perf_counter()
        try:
            device.ws = await connect(ws_url, additional_headers={"Authorization": f"Bearer {device.token}"},
                                      open_timeout=timeout_s, max_size=1 << 20, ping_interval=20, ping_timeout=20)
        except InvalidStatus as error:
            stats.fail("GET /v1/relay", str(error.response.status_code))
            return
        except (OSError, asyncio.TimeoutError) as error:
            stats.fail("GET /v1/relay", type(error).__name__)
            return
        stats.connect_ms.append((time.perf_counter() - start) * 1000)
        stats.connected += 1


async def reader(device: Device, stats: Stats) -> None:
    """Every frame the relay delivers to one device: presence, errors and forwarded frames."""
    try:
        async for message in device.ws:
            now = time.perf_counter()
            if isinstance(message, bytes):
                key = (device.device_id, "binary", message[4:20].hex() + message[23:27].hex())
            else:
                frame = json.loads(message)
                if frame.get("op") == "presence":
                    device.presence += 1
                    continue
                if frame.get("op") == "error":
                    code = frame.get("code", "?")
                    stats.relay_errors[code] = stats.relay_errors.get(code, 0) + 1
                    continue
                key = (device.device_id, "text", frame.get("env", {}).get("id"))
            sent = stats.pending.pop(key, None)
            if sent is not None:
                stats.latency_ms[key[1]].append((now - sent) * 1000)
    except ConnectionClosed as closed:
        device.closed = str(closed.rcvd.code if closed.rcvd else "no close frame")


def _uuid7() -> str:
    ms = int(time.time() * 1000)
    raw = bytearray(ms.to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


async def sender(device: Device, stats: Stats, frames: int, interval_s: float, payload: int, binary: bool) -> None:
    await asyncio.sleep(secrets.randbelow(1000) / 1000 * interval_s)  # spread the senders over one interval
    for n in range(frames):
        if device.ws is None or device.closed:
            return
        if binary and n % 2:
            seq = struct.pack(">I", n)
            inner = b"HL\x01" + seq + struct.pack(">I", n * 20) + os.urandom(max(payload, 40))
            frame = b"HR\x01\x01" + uuid_bytes(device.peer) + inner
            key = (device.peer, "binary", uuid_bytes(device.device_id).hex() + seq.hex())
            kind = "binary"
        else:
            env = {"v": 1, "type": "sms", "id": _uuid7(), "ts": int(time.time() * 1000),
                   "payload": base64.b64encode(os.urandom(max(payload, 40))).decode()}
            frame = json.dumps({"to": device.peer, "env": env}, separators=(",", ":"))
            key = (device.peer, "text", env["id"])
            kind = "text"
        stats.pending[key] = time.perf_counter()
        try:
            await device.ws.send(frame)
        except ConnectionClosed:
            stats.pending.pop(key, None)
            return
        stats.sent[kind] += 1
        if n + 1 < frames:
            await asyncio.sleep(interval_s)


def raise_fd_limit() -> int:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = hard if hard != resource.RLIM_INFINITY else 65536
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(want, 65536), hard))
    except (ValueError, OSError):
        pass
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def _ws_url(base: str) -> str:
    return ("wss://" if base.startswith("https://") else "ws://") + base.split("://", 1)[1].rstrip("/") + "/v1/relay"


async def run(args) -> dict:
    stats = Stats()
    seed = args.seed or secrets.token_hex(8)
    devices = []
    for i in range(args.devices):
        platform = "android" if i % 2 == 0 else CLIENT_PLATFORMS[(i // 2) % 2]
        digest = f"relay load {seed} device {i}".encode()
        devices.append(Device(i, hashlib.sha256(digest).digest(), platform))
    relay = Relay(args.relay, args.http_concurrency, not args.no_xff, args.timeout_s)
    started = time.perf_counter()
    ok = await asyncio.gather(*(register(relay, d, stats) for d in devices))
    registered = [d for d, good in zip(devices, ok) if good]
    await asyncio.gather(*(pair_up(relay, p, c, stats) for p, c in zip(devices[0::2], devices[1::2])
                           if p.token and c.token))
    paired = [d for d in registered if d.peer]
    gate = asyncio.Semaphore(args.connect_concurrency)
    await asyncio.gather(*(open_socket(args.ws_url or _ws_url(args.relay), d, stats, gate, args.timeout_s)
                           for d in paired))
    live = [d for d in paired if d.ws is not None]
    readers = [asyncio.create_task(reader(d, stats)) for d in live]
    setup_s = time.perf_counter() - started
    await asyncio.sleep(args.settle_s)  # presence round
    peers_live = {d.device_id for d in live}
    senders = [d for d in live if d.peer in peers_live]
    await asyncio.gather(*(sender(d, stats, args.frames, args.interval_ms / 1000, args.payload_bytes, args.binary)
                           for d in senders))
    deadline = time.perf_counter() + args.drain_s
    while stats.pending and time.perf_counter() < deadline:
        await asyncio.sleep(0.05)
    for d in live:
        if d.closed and d.closed != "1000":
            stats.closes[d.closed] = stats.closes.get(d.closed, 0) + 1
    await asyncio.gather(*(d.ws.close() for d in live), return_exceptions=True)
    await asyncio.gather(*readers, return_exceptions=True)
    if args.cleanup:
        await asyncio.gather(*(remove(relay, d, stats) for d in registered))
    return report(args, stats, devices, live, setup_s, seed)


async def remove(relay: Relay, device: Device, stats: Stats) -> None:
    """--cleanup: the device removes itself from the relay, keeping nothing (SET-02 API 2, revoke_pairs=false)."""
    status, reply = await relay.call("DELETE", "/v1/devices/me?revoke_pairs=false", None, device, device.token)
    if status != 204:
        stats.fail("DELETE /v1/devices/me", _code(status, reply))


def _dist(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"count": len(values), "p50_ms": round(percentile(values, 50), 2), "p95_ms": round(percentile(values, 95), 2),
            "p99_ms": round(percentile(values, 99), 2), "max_ms": round(max(values), 2)}


def report(args, stats: Stats, devices: list[Device], live: list[Device], setup_s: float, seed: str) -> dict:
    received = {k: len(v) for k, v in stats.latency_ms.items()}
    lost = {k: stats.sent[k] - received[k] for k in stats.sent}
    return {"relay": args.relay, "seed": seed, "devices": len(devices), "registered": len(stats.register_ms),
            "pairs": stats.pairs, "connected": stats.connected,
            "presence_frames": sum(d.presence for d in live), "setup_s": round(setup_s, 2),
            "failures": stats.failures, "relay_errors": stats.relay_errors, "unexpected_closes": stats.closes,
            "sent": stats.sent, "received": received, "lost": lost,
            "register": _dist(stats.register_ms), "connect": _dist(stats.connect_ms),
            "forward_text": _dist(stats.latency_ms["text"]), "forward_binary": _dist(stats.latency_ms["binary"])}


def print_report(r: dict) -> None:
    print(f"relay {r['relay']} — seed {r['seed']}")
    print(f"devices {r['devices']}: registered {r['registered']}, pairs {r['pairs']}, connected {r['connected']}, "
          f"presence frames {r['presence_frames']}, setup {r['setup_s']} s")
    for name in ("failures", "relay_errors", "unexpected_closes"):
        for key, count in sorted(r[name].items()):
            print(f"  {name.replace('_', ' ')}: {key} × {count}")
    print(f"frames sent {r['sent']}, received {r['received']}, lost {r['lost']}")
    for name in ("register", "connect", "forward_text", "forward_binary"):
        d = r[name]
        if d:
            print(f"  {name:15} n={d['count']:<6} p50={d['p50_ms']:.1f} p95={d['p95_ms']:.1f} p99={d['p99_ms']:.1f} "
                  f"max={d['max_ms']:.1f} ms")


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--relay", required=True, help="base URL of the relay, e.g. http://127.0.0.1:8080")
    parser.add_argument("--ws-url", help="WebSocket URL of /v1/relay when it differs from the base URL")
    parser.add_argument("--devices", type=int, default=1000, help="fake devices, an even number (default 1000)")
    parser.add_argument("--frames", type=int, default=10, help="frames each device sends to its peer")
    parser.add_argument("--interval-ms", type=float, default=1000.0, help="time between two frames of a device")
    parser.add_argument("--payload-bytes", type=int, default=200, help="random ciphertext bytes per frame")
    parser.add_argument("--binary", action="store_true", help="alternate text wrappers with binary HR frames")
    parser.add_argument("--no-xff", action="store_true", help="do not send X-Forwarded-For (≤ 10 devices)")
    parser.add_argument("--http-concurrency", type=int, default=32, help="REST calls in flight")
    parser.add_argument("--connect-concurrency", type=int, default=100, help="WebSocket handshakes in flight")
    parser.add_argument("--timeout-s", type=float, default=15.0, help="timeout of one REST call or handshake")
    parser.add_argument("--settle-s", type=float, default=1.0, help="wait after connecting, before sending")
    parser.add_argument("--drain-s", type=float, default=10.0, help="how long to wait for frames in flight")
    parser.add_argument("--seed", help="fixes the device keys (hex); random by default")
    parser.add_argument("--cleanup", action="store_true", help="remove the devices from the relay afterwards")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--check", action="store_true", help="exit 1 on any failure, error, close or lost frame")
    args = parser.parse_args(argv)
    if args.devices < 2 or args.devices % 2:
        parser.error("--devices must be an even number ≥ 2")
    return args


def check_failed(result: dict) -> bool:
    """--check: any failed step, relay error, unexpected close, lost frame or device left unconnected."""
    return bool(result["failures"] or result["relay_errors"] or result["unexpected_closes"]
                or any(result["lost"].values()) or result["connected"] < result["devices"])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raise_fd_limit()
    result = asyncio.run(run(args))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)
    return 1 if args.check and check_failed(result) else 0


if __name__ == "__main__":
    sys.exit(main())
