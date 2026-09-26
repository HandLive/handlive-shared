"""Parse the benchmark lines HandLive apps emit (format HLBENCH/1, see README.md).

A line can sit inside any log output (adb logcat, macOS `log stream`, a file): everything before the marker
`HLBENCH/1 ` is ignored. After it come space-separated `key=value` pairs; values never contain spaces.

    HLBENCH/1 wall=1727151100123.456 mono=81234567890123 dev=8c7d6e5f role=android ev=clip_read clip=0192f3e0-... kind=text bytes=27 source=auto
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "HLBENCH/1 "
ROLES = {"android", "macos", "ios"}
# Event names and the fields each one must carry (besides wall, dev, role, ev).
EVENTS: dict[str, set[str]] = {
    "copy_detected": set(),
    "clip_read": {"clip", "kind", "bytes"},
    "clip_sent": {"clip", "peer"},
    "clip_received": {"clip", "peer", "kind", "bytes"},
    "clip_applied": {"clip"},
    "ack_sent": {"clip", "peer", "status"},
    "ack_received": {"clip", "peer", "status"},
    "state": {"to"},
    "net": {"change"},
    "wake": set(),
    # SMS (Phase 2): new SMS notification (SMS-02) and reply confirmed as Sent (SMS-04); see README.md.
    "sms_detected": {"msg", "box", "onchange"},
    "sms_new_sent": {"msg", "peer", "via"},
    "sms_new_received": {"msg", "peer"},
    "sms_notified": {"msg"},
    "sms_push_sent": {"msg", "peer"},
    "sms_push_shown": {"msg"},
    "sms_send_tap": {"local"},
    "sms_bubble": {"local"},
    "sms_send_sent": {"local", "peer", "attempt", "via"},
    "sms_send_received": {"local", "peer"},
    "sms_send_ack_sent": {"local", "peer", "ok"},
    "sms_send_ack_received": {"local", "peer", "ok"},
    "sms_radio_done": {"local", "result"},
    "sms_status_sent": {"local", "peer", "status"},
    "sms_status_received": {"local", "status"},
}
KEY_VALUE = re.compile(r"^([a-z_]+)=(\S+)$")


@dataclass(frozen=True)
class Event:
    wall_ms: float  # wall clock of the emitting device, ms since the Unix epoch
    mono_ns: int | None  # monotonic clock of the emitting device (includes sleep), ns
    dev: str  # emitting device: first 8 hex digits of its device_id
    role: str  # android, macos or ios
    ev: str
    fields: dict[str, str] = field(default_factory=dict)
    where: str = ""  # file:line, for messages

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.fields.get(name, default)

    def mono_ms(self) -> float | None:
        return None if self.mono_ns is None else self.mono_ns / 1e6


@dataclass
class Log:
    events: list[Event] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # lines with the marker that could not be used

    def of(self, ev: str) -> list[Event]:
        return [e for e in self.events if e.ev == ev]


def parse_line(text: str, where: str = "") -> Event:
    """Parse one line that contains the marker; raises ValueError with the reason otherwise."""
    start = text.find(MARKER)
    if start < 0:
        raise ValueError("no HLBENCH/1 marker")
    pairs: dict[str, str] = {}
    for token in text[start + len(MARKER):].split():
        match = KEY_VALUE.match(token)
        if not match:
            raise ValueError(f"not key=value: {token!r}")
        key, value = match.groups()
        if key in pairs:
            raise ValueError(f"field {key} repeated")
        pairs[key] = value
    missing = [k for k in ("wall", "dev", "role", "ev") if k not in pairs]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    ev, role = pairs.pop("ev"), pairs.pop("role")
    if ev not in EVENTS:
        raise ValueError(f"unknown event {ev!r}")
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    wall = float(pairs.pop("wall"))
    mono_text = pairs.pop("mono", None)
    mono = int(mono_text) if mono_text is not None else None
    dev = pairs.pop("dev")
    lacking = sorted(EVENTS[ev] - set(pairs))
    if lacking:
        raise ValueError(f"{ev} needs {', '.join(lacking)}")
    return Event(wall, mono, dev, role, ev, pairs, where)


def load(paths: list[Path]) -> Log:
    """Every marked line of the given files, sorted per device by monotonic time (wall time if absent)."""
    log = Log()
    for path in paths:
        for number, text in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if MARKER not in text:
                continue
            where = f"{path.name}:{number}"
            try:
                log.events.append(parse_line(text, where))
            except ValueError as exc:
                log.problems.append(f"{where}: {exc}")
    log.events.sort(key=lambda e: (e.dev, e.mono_ns if e.mono_ns is not None else e.wall_ms * 1e6))
    return log


def local_interval_ms(start: Event, end: Event) -> float:
    """Interval between two events of the same device: monotonic clock when both have it, else wall clock."""
    assert start.dev == end.dev, "local interval needs one device"
    if start.mono_ns is not None and end.mono_ns is not None:
        return (end.mono_ns - start.mono_ns) / 1e6
    return end.wall_ms - start.wall_ms


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty list."""
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))  # ceil(n * q / 100), at least 1
    return ordered[int(rank) - 1]
