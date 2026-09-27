"""PASS/FAIL results with their evidence, and excerpts of the stack's logs taken from a byte offset on."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Result:
    name: str
    ok: bool
    evidence: list[str] = field(default_factory=list)

    def print(self) -> None:
        print(f"{'PASS' if self.ok else 'FAIL'} {self.name}")
        for line in self.evidence:
            print(f"     {line}")


def offset(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def excerpt(path: Path, start: int, pattern: str | None = None, limit: int = 40) -> list[str]:
    """Lines written to `path` after byte `start` that match `pattern` (all when None), at most `limit` (the last)."""
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(start)
        text = f.read().decode("utf-8", "replace")
    lines = [ANSI.sub("", line) for line in text.splitlines()]
    if pattern:
        rx = re.compile(pattern)
        lines = [line for line in lines if rx.search(line)]
    return lines[-limit:]


def summarize(results: list[Result]) -> int:
    for result in results:
        result.print()
    failed = [r.name for r in results if not r.ok]
    print(f"relay stack checks: {len(results) - len(failed)} passed, {len(failed)} failed"
          + (f" ({', '.join(failed)})" if failed else ""))
    return 1 if failed else 0
