"""Run relay_load.py against the in-process relay_load_fake.py (CI; needs requirements-load.txt).

    tools/.venv/bin/python tools/bench/relay_load_self_test.py

1. 20 devices with one X-Forwarded-For address each: every device registers, pairs, connects and receives all of
   its peer's text and binary frames; the devices are removed afterwards.
2. 12 devices without X-Forwarded-For: the 11th and 12th registration from one IP get 429 RATE_LIMITED, which the
   report counts, and --check fails.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relay_load  # noqa: E402
from relay_load_fake import FakeRelay  # noqa: E402


async def scenarios() -> list[tuple[str, bool, str]]:
    fake = FakeRelay()
    await fake.start()
    base = ["--relay", f"http://127.0.0.1:{fake.rest_port}", "--ws-url", f"ws://127.0.0.1:{fake.ws_port}/v1/relay",
            "--interval-ms", "20", "--settle-s", "0.2", "--drain-s", "3", "--timeout-s", "5"]
    out = []
    try:
        r = await relay_load.run(relay_load.parse_args(base + ["--devices", "20", "--frames", "4", "--binary",
                                                               "--cleanup"]))
        out.append(("20 devices registered, paired and connected",
                    (r["registered"], r["pairs"], r["connected"]) == (20, 10, 20), str(r)))
        out.append(("no failure, relay error or close", not (r["failures"] or r["relay_errors"]
                                                             or r["unexpected_closes"]), str(r)))
        out.append(("every text and binary frame arrived", r["sent"] == {"text": 40, "binary": 40}
                    and r["lost"] == {"text": 0, "binary": 0}, f"{r['sent']} {r['lost']}"))
        out.append(("latency percentiles reported", r["forward_text"]["count"] == 40
                    and r["forward_binary"]["count"] == 40 and r["forward_text"]["p95_ms"] > 0, str(r)))
        out.append(("presence received on connect", r["presence_frames"] >= 20, str(r["presence_frames"])))
        out.append(("devices removed by --cleanup", not fake.devices, str(len(fake.devices))))
        out.append(("--check passes", not relay_load.check_failed(r), str(r)))
        r = await relay_load.run(relay_load.parse_args(base + ["--devices", "12", "--frames", "2", "--no-xff"]))
        out.append(("registrations past 10 per IP are refused and counted",
                    r["failures"] == {"POST /v1/devices: 429 RATE_LIMITED": 2} and r["registered"] == 10, str(r)))
        out.append(("only complete pairs connect, nothing lost", r["connected"] == 2 * r["pairs"] >= 8
                    and not any(r["lost"].values()), str(r)))
        out.append(("--check fails", relay_load.check_failed(r), str(r)))
    finally:
        await fake.stop()
    return out


def main() -> int:
    results = asyncio.run(scenarios())
    failed = [(name, detail) for name, ok, detail in results if not ok]
    for name, detail in failed:
        print(f"  FAIL {name}: {detail[:400]}")
    print(f"relay load self-test: {len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
