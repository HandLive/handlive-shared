"""Clock offset between two devices from their own request/ack exchanges (the NTP method, RFC 5905 §8).

Every `clipboard/push` is acknowledged, and both sides log it: a sends at t1 and receives the ack at t4 (a's
clock), b receives at t2 and acks at t3 (b's clock). Then

    offset(b - a) = ((t2 - t1) + (t3 - t4)) / 2      delay = (t4 - t1) - (t3 - t2)

and the offset error is at most delay / 2. The exchange with the smallest delay near the moment of interest
gives the best offset; this also follows the slow drift of the two clocks during a session.
"""

from __future__ import annotations

from dataclasses import dataclass

from bench_log import Log


@dataclass(frozen=True)
class Exchange:
    a: str  # sent the request, received the ack
    b: str  # received the request, sent the ack
    t1: float
    t2: float
    t3: float
    t4: float
    clip: str

    @property
    def offset(self) -> float:
        """Clock of b minus clock of a, in ms."""
        return ((self.t2 - self.t1) + (self.t3 - self.t4)) / 2

    @property
    def delay(self) -> float:
        """Network round trip without b's processing, in ms."""
        return (self.t4 - self.t1) - (self.t3 - self.t2)

    @property
    def at(self) -> float:
        """Middle of the exchange on a's clock."""
        return (self.t1 + self.t4) / 2


@dataclass(frozen=True)
class Offset:
    value: float  # clock of the other device minus the reference clock, ms
    error: float  # bound of the error, ms (delay / 2), or nan when assumed
    method: str  # "exchange", "exchange (outside window)", "manual", "chain", "assumed 0"


def exchanges(log: Log) -> list[Exchange]:
    """Complete request/ack quadruples found in the log (all four events present)."""
    index = {}
    for e in log.events:
        if e.ev in ("clip_sent", "clip_received", "ack_sent", "ack_received"):
            index.setdefault((e.ev, e.dev, e.get("peer"), e.get("clip")), e)
    out = []
    for (ev, a, b, clip), sent in index.items():
        if ev != "clip_sent":
            continue
        received = index.get(("clip_received", b, a, clip))
        acked = index.get(("ack_sent", b, a, clip))
        back = index.get(("ack_received", a, b, clip))
        if received and acked and back:
            out.append(Exchange(a, b, sent.wall_ms, received.wall_ms, acked.wall_ms, back.wall_ms, clip))
    return out


class ClockModel:
    """Offsets between devices, chosen per moment from the exchanges, manual values or an assumption."""

    def __init__(self, found: list[Exchange], manual: dict[tuple[str, str], float] | None = None,
                 window_ms: float = 120_000.0) -> None:
        self.found = found
        self.manual = manual or {}
        self.window_ms = window_ms

    def _direct(self, ref: str, other: str, at: float) -> Offset | None:
        # Exchanges in either direction, expressed as (moment on ref's clock, offset other - ref, delay).
        samples = [(x.at, x.offset, x.delay) for x in self.found if (x.a, x.b) == (ref, other)]
        samples += [(x.at + x.offset, -x.offset, x.delay) for x in self.found if (x.a, x.b) == (other, ref)]
        if samples:
            near = [s for s in samples if abs(s[0] - at) <= self.window_ms]
            _, value, delay = min(near or samples, key=lambda s: s[2])
            return Offset(value, delay / 2, "exchange" if near else "exchange (outside window)")
        if (ref, other) in self.manual:
            return Offset(self.manual[(ref, other)], float("nan"), "manual")
        if (other, ref) in self.manual:
            return Offset(-self.manual[(other, ref)], float("nan"), "manual")
        return None

    def offset(self, ref: str, other: str, at: float) -> Offset:
        """Clock of `other` minus clock of `ref` around the moment `at` (ref's clock)."""
        if ref == other:
            return Offset(0.0, 0.0, "same device")
        direct = self._direct(ref, other, at)
        if direct:
            return direct
        devices = {x.a for x in self.found} | {x.b for x in self.found} | {d for pair in self.manual for d in pair}
        for middle in sorted(devices - {ref, other}):  # one intermediate device, e.g. Mac -> phone -> iPad
            first = self._direct(ref, middle, at)
            second = self._direct(middle, other, at + first.value) if first else None
            if first and second:
                return Offset(first.value + second.value, first.error + second.error, "chain")
        return Offset(0.0, float("nan"), "assumed 0")

    def to_ref(self, wall_ms: float, dev: str, ref: str) -> tuple[float, Offset]:
        """A wall time of `dev` expressed on `ref`'s clock."""
        offset = self.offset(ref, dev, wall_ms)
        return wall_ms - offset.value, offset
