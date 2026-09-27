"""PASS/FAIL per step with the observed latency, printed as the run goes and kept for a JSON summary."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class StepResult:
    scenario: str
    device: str
    name: str
    spec: str
    status: str            # PASS | FAIL | SKIP | INFO
    detail: str = ""
    latency_ms: float | None = None
    target_ms: float | None = None


class Recorder:
    def __init__(self, device: str, out: Path | None = None) -> None:
        self.device = device
        self.out = out
        self.scenario = ""
        self.results: list[StepResult] = []

    def begin(self, scenario: str) -> None:
        self.scenario = scenario
        print(f"\n=== {scenario} on {self.device} ===", flush=True)

    def record(self, name: str, spec: str, ok: bool | None, detail: str = "", latency_ms: float | None = None,
               target_ms: float | None = None) -> bool:
        status = "INFO" if ok is None else ("PASS" if ok else "FAIL")
        r = StepResult(self.scenario, self.device, name, spec, status, detail, latency_ms, target_ms)
        self.results.append(r)
        lat = "" if latency_ms is None else f" — {latency_ms:.0f} ms" + (
            f" (target {target_ms:.0f} ms)" if target_ms else "")
        print(f"{status:4}  [{self.scenario}] {spec}: {name}{lat}" + (f" — {detail}" if detail else ""), flush=True)
        self._flush()
        return bool(ok) if ok is not None else True

    def check(self, name: str, spec: str, ok: bool, detail: str = "", **kw) -> bool:
        return self.record(name, spec, bool(ok), detail, **kw)

    def info(self, name: str, spec: str, detail: str = "", **kw) -> None:
        self.record(name, spec, None, detail, **kw)

    def skip(self, name: str, spec: str, reason: str) -> None:
        r = StepResult(self.scenario, self.device, name, spec, "SKIP", reason)
        self.results.append(r)
        print(f"SKIP  [{self.scenario}] {spec}: {name} — {reason}", flush=True)
        self._flush()

    def failed(self, scenario: str | None = None) -> int:
        return sum(1 for r in self.results if r.status == "FAIL" and scenario in (None, r.scenario))

    def summary(self) -> str:
        by: dict[str, dict[str, int]] = {}
        for r in self.results:
            by.setdefault(r.scenario, {}).setdefault(r.status, 0)
            by[r.scenario][r.status] += 1
        lines = [f"{s}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) for s, c in by.items()]
        return "\n".join(lines)

    def _flush(self) -> None:
        if self.out is not None:
            self.out.write_text(json.dumps([asdict(r) for r in self.results], indent=1), encoding="utf-8")


class Stopwatch:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def ms(self) -> float:
        return (time.monotonic() - self.t0) * 1000
