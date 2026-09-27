"""HLBENCH/1 lines of the fake Mac (role=macos), so tools/bench/*.py can read a run next to the phone's logcat.

Format and events: tools/bench/README.md. Only ids, kinds, sizes and states — never content, numbers or names.
The fake Mac logs what it really does; it posts no notification and shows no panel, so it never writes
`sms_notified`, `call_panel_shown` or `call_missed_notified`.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path


class BenchLog:
    def __init__(self, path: Path | None, device_id: str) -> None:
        self.path = path
        self.dev = device_id.replace("-", "")[:8]
        self._lock = threading.Lock()

    def line(self, ev: str, **fields) -> str:
        wall = time.time_ns() / 1e6
        parts = [f"HLBENCH/1 wall={wall:.3f} mono={time.monotonic_ns()} dev={self.dev} role=macos ev={ev}"]
        parts += [f"{k}={_value(v)}" for k, v in fields.items() if v is not None]
        text = " ".join(parts)
        if self.path is not None:
            with self._lock, self.path.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        return text


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if any(c.isspace() for c in s):
        raise ValueError(f"HLBENCH values never contain spaces: {s!r}")
    return s


def peer8(device_id: str) -> str:
    return device_id.replace("-", "")[:8]
