"""The client side of a `/v1/ctl` session (CONN-01 API 4–7, 0.6.3) over any transport (LAN WSS or a relay channel).

`open()` runs the handshake and the capability exchange; a receiver thread decrypts every inbound envelope, validates
it against shared/schemas, matches acks to requests and keeps the rest as events that scenarios wait for. The session
answers what a Mac answers on its own: a clipboard push from the phone is written ("applied") and acked (CLIP-01).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import mac_crypto as C
from bench_lines import BenchLog, peer8
from pair_store import PairRecord
from schema_check import SchemaCheck
from transport import TransportClosed

HANDSHAKE_TIMEOUT = 5.0   # 0.10 HANDSHAKE_TIMEOUT
REQUEST_TIMEOUT = 10.0    # 0.10 REQUEST_TIMEOUT


class SessionRefused(Exception):
    def __init__(self, code: str, close_code: int | None, detail: str = "") -> None:
        super().__init__(f"{code} (close {close_code}) {detail}".strip())
        self.code = code
        self.close_code = close_code


@dataclass
class Inbound:
    index: int
    type: str
    op: str | None
    data: dict | None
    env: dict
    plaintext: dict
    binary: bytes | None
    mono: float
    wall_ms: float


@dataclass
class Ack:
    env_id: str
    ts: int
    ok: bool
    data: dict | None
    error: dict | None
    latency_ms: float
    raw: dict = field(default_factory=dict)

    @property
    def code(self) -> str | None:
        return (self.error or {}).get("code")


class MacSession:
    def __init__(self, record: PairRecord, open_transport: Callable[[], object], capability: dict,
                 checker: SchemaCheck, bench: BenchLog | None = None, log: Callable[[str], None] = print) -> None:
        self.record = record
        self.open_transport = open_transport
        self.capability = capability
        self.checker = checker
        self.bench = bench or BenchLog(None, record.device_id)
        self.log = log
        self.transport = None
        self.events: list[Inbound] = []
        self.violations: list[str] = []
        self.peer_capability: dict | None = None
        self.closed: tuple[int | None, str] | None = None
        self.applied_clips: dict[str, dict] = {}
        self._acks: dict[str, tuple[dict, float]] = {}
        self._pending: dict[str, tuple[str, str, float]] = {}
        self._seen_ids: set[str] = set()
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._k_c2s = self._k_s2c = b""
        self.timings: dict[str, float] = {}

    # ----- handshake -------------------------------------------------------------------------------------------
    def open(self) -> dict:
        t0 = time.monotonic()
        self.transport = self.open_transport()
        t_tls = time.monotonic()
        self.bench.line("state", to="Handshaking", channel=self.transport.label)
        prk = bytes.fromhex(self.record.prk)
        hello = C.session_hello(prk, self.record.pair_id, self.record.device_id)
        env = C.plain_envelope("session", "hello", hello.data)
        self._check_out(env, "session", "hello", {"op": "hello", "data": hello.data})
        self.transport.send(json.dumps(env, separators=(",", ":")))
        welcome = self._recv_handshake()
        keys = C.session_keys(prk, hello, welcome, self.record.peer_device_id)
        if keys is None:
            self.transport.close(4401, "AUTH_FAILED")
            raise SessionRefused("AUTH_FAILED", 4401, "welcome mac or device_id does not match")
        self._k_c2s, self._k_s2c = keys
        t_keys = time.monotonic()
        self._thread = threading.Thread(target=self._receive_loop, name="mac-session-recv", daemon=True)
        self._thread.start()
        self.send("capability", "hello", self.capability)
        phone_cap = self.wait(lambda m: m.type == "capability" and m.op == "hello", HANDSHAKE_TIMEOUT)
        if phone_cap is None:
            raise SessionRefused("NO_CAPABILITY", self.transport.close_code, "no capability/hello from the phone")
        self.peer_capability = phone_cap.data
        t_done = time.monotonic()
        self.timings = {"connect_ms": (t_tls - t0) * 1000, "handshake_ms": (t_keys - t_tls) * 1000,
                        "capability_ms": (t_done - t_keys) * 1000, "total_ms": (t_done - t0) * 1000}
        self.bench.line("state", **{"from": "Handshaking"}, to="Connected", channel=self.transport.label)
        return self.timings

    def _recv_handshake(self) -> dict:
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise SessionRefused("TIMEOUT", None, "no session/welcome within HANDSHAKE_TIMEOUT")
            try:
                frame = self.transport.recv(left)
            except TransportClosed as exc:
                raise SessionRefused("CLOSED", exc.code, exc.reason) from exc
            if frame is None:
                continue
            env = json.loads(frame)
            self._check_in_envelope(env)
            plaintext = C.open_plain(env)
            op = plaintext.get("op")
            self._record_violations(self.checker.check_payload("session", op, plaintext), f"in session/{op}")
            if op == "error":
                code = plaintext["data"].get("code", "?")
                close_code = None
                try:
                    self.transport.recv(2.0)
                except TransportClosed as exc:
                    close_code = exc.code
                raise SessionRefused(code, close_code, plaintext["data"].get("message", ""))
            if op == "welcome":
                return plaintext["data"]
            self.violations.append(f"unexpected handshake op {op!r}")

    # ----- sending ---------------------------------------------------------------------------------------------
    def send(self, typ: str, op: str, data: dict, env_id: str | None = None, ts: int | None = None,
             validate: bool = True) -> tuple[str, int]:
        plaintext = {"op": op, "data": data}
        env = C.seal(self._k_c2s, typ, C.compact_json(plaintext).encode(), env_id=env_id, ts=ts)
        if validate:
            self._check_out(env, typ, op, plaintext)
        with self._cond:
            self._pending[env["id"]] = (typ, op, time.monotonic())
        self.transport.send(json.dumps(env, separators=(",", ":")))
        return env["id"], env["ts"]

    def send_ack(self, re: str, ok: bool, data: dict | None = None, error: dict | None = None) -> None:
        body = {"re": re, "ok": ok, **({"data": data or {}} if ok else {"error": error})}
        env = C.seal(self._k_c2s, "ack", C.compact_json(body).encode())
        self._record_violations(self.checker.errors("envelope", env) + self.checker.errors("ack", body), "out ack")
        self.transport.send(json.dumps(env, separators=(",", ":")))

    def send_chunk(self, transfer_id: str, index: int, data: bytes) -> str:
        env = C.seal(self._k_c2s, "clipboard", C.chunk_plaintext(transfer_id, index, data))
        self._record_violations(self.checker.errors("envelope", env), "out clipboard/chunk")
        self.transport.send(json.dumps(env, separators=(",", ":")))
        return env["id"]

    def request(self, typ: str, op: str, data: dict, timeout: float = REQUEST_TIMEOUT, env_id: str | None = None,
                ts: int | None = None, validate: bool = True) -> Ack | None:
        """Sends and waits for the ack (0.5.1 rule 1); None after `timeout`. A resend reuses env_id and ts."""
        t0 = time.monotonic()
        env_id, ts = self.send(typ, op, data, env_id=env_id, ts=ts, validate=validate)
        return self.wait_ack(env_id, ts, t0, timeout)

    def wait_ack(self, env_id: str, ts: int, t0: float, timeout: float = REQUEST_TIMEOUT) -> Ack | None:
        deadline = t0 + timeout
        with self._cond:
            while env_id not in self._acks:
                left = deadline - time.monotonic()
                if left <= 0 or self.closed:
                    return None
                self._cond.wait(min(left, 0.5))
            body, at = self._acks.pop(env_id)
        return Ack(env_id, ts, body.get("ok") is True, body.get("data"), body.get("error"), (at - t0) * 1000, body)

    # ----- receiving -------------------------------------------------------------------------------------------
    def mark(self) -> int:
        """A cursor for wait(): only events that arrive after this point match."""
        with self._cond:
            return len(self.events)

    def wait(self, pred: Callable[[Inbound], bool], timeout: float, after: int = 0) -> Inbound | None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for m in self.events[after:]:
                    if pred(m):
                        return m
                left = deadline - time.monotonic()
                if left <= 0 or (self.closed and not any(pred(m) for m in self.events[after:])):
                    return None
                self._cond.wait(min(left, 0.5))

    def collect(self, pred: Callable[[Inbound], bool], after: int = 0) -> list[Inbound]:
        with self._cond:
            return [m for m in self.events[after:] if pred(m)]

    def _receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self.transport.recv(0.5)
            except TransportClosed as exc:
                with self._cond:
                    self.closed = (exc.code, exc.reason)
                    self._cond.notify_all()
                self.bench.line("state", **{"from": "Connected"}, to="Backoff")
                return
            if frame is None:
                continue
            if isinstance(frame, bytes):
                self.violations.append("binary frame on /v1/ctl (0.5.2: HL frames only on /v1/stream/*)")
                continue
            try:
                self._handle_text(frame)
            except Exception as exc:  # noqa: BLE001 — a malformed message is a finding, not a harness crash
                self.violations.append(f"inbound message not handled: {exc!r}")

    def _handle_text(self, frame: str) -> None:
        mono, wall = time.monotonic(), time.time_ns() / 1e6
        env = json.loads(frame)
        self._check_in_envelope(env)
        if env["id"] in self._seen_ids:
            self.violations.append(f"duplicate envelope id from the phone ({env['type']})")
        self._seen_ids.add(env["id"])
        try:
            raw = C.open_sealed(self._k_s2c, env)
        except ValueError:
            self.violations.append(f"DECRYPT_FAILED on an inbound {env['type']} envelope")
            return
        plaintext, binary = C.parse_plaintext(raw)
        if env["type"] == "ack":
            with self._cond:
                pending = self._pending.get(plaintext.get("re"))
            if pending is None:
                self.violations.append("ack for an unknown request id")
            else:
                self._record_violations(self.checker.check_ack(pending[0], pending[1], plaintext),
                                        f"in ack of {pending[0]}/{pending[1]}")
            with self._cond:
                self._acks[plaintext.get("re")] = (plaintext, mono)
                self._cond.notify_all()
            return
        op = plaintext.get("op")
        if binary is None:
            self._record_violations(self.checker.check_payload(env["type"], op, plaintext), f"in {env['type']}/{op}")
        with self._cond:
            msg = Inbound(len(self.events), env["type"], op, plaintext.get("data"), env, plaintext, binary, mono, wall)
            self.events.append(msg)
            self._cond.notify_all()
        self._bench_inbound(msg)
        self._auto_answer(msg)

    def _bench_inbound(self, m: Inbound) -> None:
        peer = peer8(self.record.peer_device_id)
        d = m.data or {}
        if m.type == "call_event" and m.op == "state":
            self.bench.line("call_state_received", call=d.get("call_id"), env=m.env["id"], peer=peer,
                            state=d.get("state"), waiting=d.get("waiting"))
        elif m.type == "sms" and m.op == "new":
            self.bench.line("sms_new_received", msg=(d.get("message") or {}).get("message_key"), peer=peer)
        elif m.type == "sms" and m.op == "status":
            self.bench.line("sms_status_received", local=d.get("local_id"), status=d.get("status"),
                            code=d.get("error_code"))

    def _auto_answer(self, m: Inbound) -> None:
        """What M-APP does without the user: write a phone clip and ack it `applied` (CLIP-01 API 5, API 7)."""
        if m.type == "clipboard" and m.op == "push" and m.data and "text" in m.data:
            clip = m.data["clip_id"]
            peer = peer8(self.record.peer_device_id)
            size = len(m.data["text"].encode())
            self.bench.line("clip_received", clip=clip, peer=peer, kind="text", bytes=size)
            duplicate = clip in self.applied_clips
            self.applied_clips.setdefault(clip, m.data)
            self.bench.line("clip_applied", clip=clip)
            status = {"clip_id": clip, "status": "ignored", "reason": "duplicate"} if duplicate else \
                {"clip_id": clip, "status": "applied"}
            self.send_ack(m.env["id"], True, status)
            self.bench.line("ack_sent", clip=clip, peer=peer, status=status["status"])

    # ----- checks ----------------------------------------------------------------------------------------------
    def _check_out(self, env: dict, typ: str, op: str, plaintext: dict) -> None:
        errs = self.checker.errors("envelope", env) + self.checker.check_payload(typ, op, plaintext)
        if errs:
            raise ValueError(f"outgoing {typ}/{op} breaks the schema: {errs[0]}")

    def _check_in_envelope(self, env: dict) -> None:
        self._record_violations(self.checker.errors("envelope", env), f"in envelope {env.get('type')}")

    def _record_violations(self, errs: list[str], where: str) -> None:
        for e in errs[:1]:
            self.violations.append(f"{where}: {e}")

    # ----- closing ---------------------------------------------------------------------------------------------
    def close(self, bye: bool = True, reason: str = "shutdown") -> None:
        """CONN-02 step 8: session/bye, then close 1000 (a relayed session keeps its link, CONN-02 API 4)."""
        if self.transport is None:
            return
        if bye and not self.closed:
            try:
                self.send("session", "bye", {"reason": reason})
            except (TransportClosed, OSError):
                pass
        self._stop.set()
        self.transport.close(1000, "")
        if self._thread:
            self._thread.join(timeout=3)

    def abort(self) -> None:
        """Leaves without session/bye or a close frame (the network went away)."""
        self._stop.set()
        if self.transport is not None:
            self.transport.abort()
        if self._thread:
            self._thread.join(timeout=3)
