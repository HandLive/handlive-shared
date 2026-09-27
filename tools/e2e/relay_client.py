"""The fake client on the local relay stack (relay_stack/, CONN-03, CONN-04): registration and JWT, pair
registration, the push token, `/v1/relay`, and a relay channel that carries a `/v1/ctl` session to one peer.

The session is the same as on the LAN (mac_session.py); only the transport changes. Outgoing envelopes are wrapped
`{"to", "env"}`, the relay hands them over as `{"from", "env"}` (0.4.3); relay control ops (`presence`, `error`,
`pair_revoked`) are kept apart. TLS to the stack's front is verified against its test CA.
"""
from __future__ import annotations

import json
import queue
import ssl
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pair_store import PairRecord
from schema_check import SchemaCheck
from transport import TransportClosed
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "relay_stack"))
from stack_rest import FakeDevice, RelayRest, error_code, fake_xff  # noqa: E402

import mac_crypto as C  # noqa: E402


@dataclass
class RelayStack:
    """What `relay_stack.py up` wrote to relay_stack.json."""
    https: str
    wss: str
    ca_cert: str
    apns_capture: Path
    fcm_capture: Path
    apns_topic: str
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, state_dir: Path) -> "RelayStack":
        d = json.loads((state_dir / "relay_stack.json").read_text(encoding="utf-8"))
        return cls(d["relay"]["https"], d["relay"]["wss"], d["tls"]["ca_cert"], Path(d["apns"]["capture"]),
                   Path(d["fcm"]["capture"]), d["apns"]["topic"], d)

    def rest(self) -> RelayRest:
        return RelayRest(self.https, self.ca_cert)


class RelayAccount:
    """The client as a relay device: HLREG1 registration, HLAUTH1 token, pairs, push token (0.6.4, CONN-03/04)."""

    def __init__(self, stack: RelayStack, record: PairRecord, checker: SchemaCheck) -> None:
        self.stack, self.record, self.checker = stack, record, checker
        self.rest = stack.rest()
        self.device = FakeDevice(record.platform, bytes.fromhex(record.sig_seed))
        self.xff = fake_xff()

    def register(self) -> tuple[int, dict]:
        return self.device.register(self.rest, self.xff)

    @property
    def token(self) -> str:
        return self.device.token

    def register_pair(self) -> tuple[int, dict]:
        """PAIR-01 API 8 by the client, with the attestation and both signatures of this pair (idempotent)."""
        r = self.record
        body = {"pair_id": r.pair_id, "device_a": r.peer_device_id, "device_b": r.device_id,
                "created_at": r.created_at, "attestation": C.b64u(bytes.fromhex(r.attestation)),
                "sig_a": C.b64u(bytes.fromhex(r.sig_peer)), "sig_b": C.b64u(bytes.fromhex(r.sig_self))}
        errs = self.checker.errors("relay-rest#pairs-request", body)
        if errs:
            raise ValueError(errs[0])
        return self.rest.call("POST", "/v1/pairs", body, token=self.token, xff=self.xff)

    def pairs(self) -> tuple[int, dict]:
        return self.rest.call("GET", "/v1/pairs", token=self.token, xff=self.xff)

    def put_push_token(self, apns_token_hex: str) -> tuple[int, dict]:
        body = {"provider": "apns_sandbox", "token": apns_token_hex, "topic": self.stack.apns_topic}
        errs = self.checker.errors("relay-rest#push-token-request", body)
        if errs:
            raise ValueError(errs[0])
        return self.rest.call("PUT", "/v1/devices/me/push-token", body, token=self.token, xff=self.xff)


class RelayLink:
    """One `/v1/relay` WebSocket (CONN-03 API 4): wrappers per peer, control ops in `control`."""
    label = "relay"

    def __init__(self, stack: RelayStack, token: str, checker: SchemaCheck, open_timeout: float = 10) -> None:
        self.checker = checker
        ctx = ssl.create_default_context(cafile=stack.ca_cert) if stack.wss.startswith("wss:") else None
        self.ws = connect(stack.wss, ssl=ctx, additional_headers={"Authorization": f"Bearer {token}"},
                          compression=None, proxy=None, open_timeout=open_timeout, ping_interval=15, ping_timeout=10,
                          max_size=1 << 20)
        self.control: list[dict] = []
        self.violations: list[str] = []
        self._queues: dict[str, queue.Queue] = {}
        self._cond = threading.Condition()
        self.closed: tuple[int | None, str] | None = None
        self._thread = threading.Thread(target=self._read, name="relay-link", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        while True:
            try:
                frame = self.ws.recv()
            except ConnectionClosed:
                with self._cond:
                    self.closed = (self.ws.close_code, self.ws.close_reason or "")
                    self._cond.notify_all()
                for q in self._queues.values():
                    q.put(None)
                return
            if isinstance(frame, bytes):
                continue                                   # HR frames belong to /v1/stream/* (P4, P5)
            obj = json.loads(frame)
            if "env" in obj and "from" in obj:
                errs = self.checker.errors("relay-wrapper#inbound", obj)
                self.violations += [f"relay wrapper: {e}" for e in errs[:1]]
                self._queue(obj["from"]).put(json.dumps(obj["env"], separators=(",", ":")))
            else:
                op = obj.get("op", "?")
                errs = self.checker.errors(f"relay-{op}", obj) if f"relay-{op}" in self.checker.validators else []
                self.violations += [f"relay {op}: {e}" for e in errs[:1]]
                with self._cond:
                    self.control.append({**obj, "_mono": time.monotonic()})
                    self._cond.notify_all()

    def _queue(self, peer: str) -> queue.Queue:
        with self._cond:
            return self._queues.setdefault(peer, queue.Queue())

    def wait_control(self, pred, timeout: float, after: int = 0) -> dict | None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for m in self.control[after:]:
                    if pred(m):
                        return m
                left = deadline - time.monotonic()
                if left <= 0 or self.closed:
                    return None
                self._cond.wait(min(left, 0.5))

    def send_wrapped(self, peer: str, env_text: str) -> None:
        wrapper = {"to": peer, "env": json.loads(env_text)}
        errs = self.checker.errors("relay-wrapper#outbound", wrapper)
        if errs:
            raise ValueError(errs[0])
        try:
            self.ws.send(json.dumps(wrapper, separators=(",", ":")))
        except ConnectionClosed as exc:
            raise TransportClosed(self.ws.close_code, "relay link closed") from exc

    def channel(self, peer: str) -> "RelayChannel":
        return RelayChannel(self, peer)

    def close(self) -> None:
        try:
            self.ws.close(1000, "")
        except (OSError, ConnectionClosed):
            pass


class RelayChannel:
    """A transport for MacSession to one peer through the relay; closing it keeps the link (CONN-02 API 4)."""
    label = "relay"
    cert_sha256 = None

    def __init__(self, link: RelayLink, peer: str) -> None:
        self.link, self.peer = link, peer
        self._q = link._queue(peer)
        while not self._q.empty():                          # leftovers of an earlier session with this peer
            self._q.get_nowait()
        self._closed = False

    def send(self, text: str) -> None:
        if self._closed:
            raise TransportClosed(None, "relay channel closed")
        self.link.send_wrapped(self.peer, text)

    def recv(self, timeout: float) -> str | None:
        if self._closed:
            raise TransportClosed(None, "relay channel closed")
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            self._closed = True
            raise TransportClosed(self.link.closed[0] if self.link.closed else None, "relay link closed")
        return item

    @property
    def close_code(self) -> int | None:
        return None

    @property
    def close_reason(self) -> str:
        return ""

    def close(self, code: int = 1000, reason: str = "") -> None:
        self._closed = True

    def abort(self) -> None:
        self._closed = True


def relay_errors(link: RelayLink, after: int = 0) -> list[str]:
    return [f"{m.get('code')}" for m in link.control[after:] if m.get("op") == "error"]


__all__ = ["RelayAccount", "RelayChannel", "RelayLink", "RelayStack", "error_code", "relay_errors"]
