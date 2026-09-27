"""The client side of PAIR-01 over `/v1/pair` with a PIN (A1–A5, API 2–6), as M-APP runs it.

One call is one connection: `pair/hello` (mode pin) → the phone waits for the user's PIN, then `pair/offer` → check
the offer's mac with our PIN, the self-certifying device_id and the TLS certificate of this very connection →
`pair/confirm` → `pair/done` → close 1000. A wrong PIN is answered with `pair/error PIN_INVALID` and the attempts left.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable

import mac_crypto as C
from pair_store import PairRecord
from schema_check import SchemaCheck
from transport import TransportClosed


@dataclass
class PairAttempt:
    outcome: str                    # paired | pin_mismatch | refused | failed
    code: str | None = None         # the phone's pair/error code, or our own check that failed
    offer: dict | None = None
    security_code: str = ""
    violations: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)


class PinPairing:
    def __init__(self, record: PairRecord, checker: SchemaCheck, open_transport: Callable[[], object]) -> None:
        self.record = record
        self.checker = checker
        self.open_transport = open_transport

    def attempt(self, pin: str, attempts_left_if_wrong: int, offer_timeout: float = 130.0) -> PairAttempt:
        res = PairAttempt("failed")
        t0 = time.monotonic()
        transport = self.open_transport()
        ident = self.record.identity
        nonce_c = os.urandom(32)
        try:
            self._send(transport, "hello", {
                "mode": "pin", "device_id": ident.device_id, "nonce": C.b64u(nonce_c), "name": self.record.name,
                "platform": self.record.platform, "model": self.record.model, "ik_sig_pub": C.b64u(ident.sig_pub),
                "ik_dh_pub": C.b64u(ident.dh_pub)}, res)
            op, offer = self._recv(transport, offer_timeout, res)       # the phone waits for the typed PIN
            res.timings["offer_ms"] = (time.monotonic() - t0) * 1000
            if op == "error":
                res.outcome, res.code = "refused", offer.get("code")
                return res
            if op != "offer":
                res.code = f"unexpected {op}"
                return res
            res.offer = offer
            check = C.check_pin_offer(pin, ident, self.record.name, nonce_c, offer, transport.cert_sha256)
            if not check.ok:
                if check.reason == "mac":           # A5: our PIN does not produce the phone's mac
                    self._send(transport, "error", {"code": "PIN_INVALID", "message": "PIN does not match",
                                                    "attempts_left": attempts_left_if_wrong}, res)
                    res.outcome, res.code = "pin_mismatch", "PIN_INVALID"
                else:                               # E4: never say which check failed
                    self._send(transport, "error", {"code": "AUTH_FAILED", "message": "Pairing check failed"}, res)
                    res.code = f"AUTH_FAILED ({check.reason})"
                return res
            secrets_ = C.build_confirm(ident, offer, check)
            t_confirm = time.monotonic()
            self._send(transport, "confirm", secrets_.confirm, res)
            op, done = self._recv(transport, 15.0, res)
            res.timings["confirm_to_done_ms"] = (time.monotonic() - t_confirm) * 1000
            if op != "done":
                res.outcome, res.code = ("refused", done.get("code")) if op == "error" else ("failed", f"got {op}")
                return res
            failed = C.check_done(done, offer, check, secrets_)
            if failed:
                res.code = f"AUTH_FAILED (done {failed})"
                return res
            self._store(offer, transport.cert_sha256, secrets_, C.b64u_decode(done["sig"], 64))
            res.outcome, res.security_code = "paired", self.record.security_code
            res.timings["total_ms"] = (time.monotonic() - t0) * 1000
            return res
        except TransportClosed as exc:
            res.code = f"closed {exc.code}"
            return res
        finally:
            transport.close(1000, "")

    def _store(self, offer: dict, tls: bytes, s: C.PairSecrets, sig_peer: bytes) -> None:
        r = self.record
        r.pair_id, r.created_at, r.prk = s.pair_id, s.created_at, s.prk.hex()
        r.peer_device_id, r.peer_name, r.peer_model = offer["device_id"], offer["name"], offer["model"]
        r.peer_os = offer["os_version"]
        r.peer_ik_sig_pub = C.b64u_decode(offer["ik_sig_pub"], 32).hex()
        r.peer_ik_dh_pub = C.b64u_decode(offer["ik_dh_pub"], 32).hex()
        r.peer_tls_sha256 = tls.hex()
        r.attestation, r.sig_self, r.sig_peer = s.attestation.hex(), s.sig_c.hex(), sig_peer.hex()
        r.security_code = C.security_code(s.attestation)
        r.relay_registered = False
        r.cursors = {}

    def _send(self, transport, op: str, data: dict, res: PairAttempt) -> None:
        env = C.plain_envelope("pair", op, data)
        errs = self.checker.errors("envelope", env) + self.checker.check_payload("pair", op, {"op": op, "data": data})
        res.violations += [f"out pair/{op}: {e}" for e in errs[:1]]
        transport.send(json.dumps(env, separators=(",", ":")))

    def _recv(self, transport, timeout: float, res: PairAttempt) -> tuple[str | None, dict]:
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            frame = transport.recv(min(left, 1.0))
            if frame is None:
                continue
            env = json.loads(frame)
            plaintext = C.open_plain(env)
            op = plaintext.get("op")
            errs = self.checker.errors("envelope", env) + self.checker.check_payload("pair", op, plaintext)
            res.violations += [f"in pair/{op}: {e}" for e in errs[:1]]
            return op, plaintext.get("data") or {}
        return None, {}
