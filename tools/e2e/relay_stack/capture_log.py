"""The capture files of the mock providers: one JSON object per line, appended as requests arrive.

Every line records what a provider would see — path, headers without `authorization`, the JSON body — plus the
verdict of the mock's own checks (provider token, OAuth assertion, access token). Bearer tokens, the provider JWT
and the OAuth assertion are never written; the claims they carried are, once verified.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie"}


class CaptureLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    def append(self, record: dict) -> None:
        record = {"ts": int(time.time() * 1000), **record}
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def public_headers(headers) -> dict:
    """Header name → value, lowercase names, without credentials."""
    return {k.lower(): v for k, v in headers if k.lower() not in SECRET_HEADERS}


def read_captures(path: Path, since_ms: int = 0) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("ts", 0) >= since_ms:
                out.append(record)
    return out
