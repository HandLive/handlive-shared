"""Tests of the bench scripts on synthetic logs whose true timings are known (SMS: sms_self_test.py).

    python3 tools/bench/self_test.py

The phone's clock runs 1234.5 ms ahead of the Mac's, the network takes 3 ms each way; the scripts must find the
offset from the ack exchanges and recover the exact latencies and reconnect times.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_latency  # noqa: E402
import reconnect_time  # noqa: E402
import sms_self_test  # noqa: E402
from bench_log import load, parse_line, percentile  # noqa: E402
from clock_sync import ClockModel, exchanges  # noqa: E402

MAC, PHONE, IPAD = "5b1f8c2e", "8c7d6e5f", "a1b2c3d4"
ROLE = {MAC: "macos", PHONE: "android", IPAD: "ios"}
SKEW = {MAC: 0.0, PHONE: 1234.5, IPAD: -250.0}  # device clock minus true time, ms
BOOT = {MAC: 5_000_000.0, PHONE: 9_000_000.0, IPAD: 7_000_000.0}  # monotonic clock at true time 0, ms
T0 = 1_727_151_100_000.0


def line(dev: str, true_ms: float, ev: str, **fields) -> str:
    wall = T0 + true_ms + SKEW[dev]
    mono = int((BOOT[dev] + true_ms) * 1e6)
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    prefix = "09-25 22:10:01.123  4242  4242 I HLBENCH: " if ROLE[dev] == "android" else "2026-09-25 22:10:01.1 I HandLive[1]: "
    return f"{prefix}HLBENCH/1 wall={wall:.3f} mono={mono} dev={dev} role={ROLE[dev]} ev={ev} {extra}".rstrip()


def clip(logs: dict, sender: str, receiver: str, start: float, clip_id: str, kind: str, size: int,
         apply_ms: float, net_ms: float = 3.0, detect_ms: float | None = None) -> float:
    """Log one transfer; returns the true latency (clip_read -> clip_applied)."""
    if detect_ms is not None:
        logs[sender].append(line(sender, start - detect_ms, "copy_detected"))
    logs[sender].append(line(sender, start, "clip_read", clip=clip_id, kind=kind, bytes=size, source="auto"))
    logs[sender].append(line(sender, start + 1, "clip_sent", clip=clip_id, peer=receiver))
    logs[receiver].append(line(receiver, start + 1 + net_ms, "clip_received", clip=clip_id, peer=sender, kind=kind,
                               bytes=size))
    applied = start + 1 + net_ms + apply_ms
    logs[receiver].append(line(receiver, applied, "clip_applied", clip=clip_id))
    logs[receiver].append(line(receiver, applied + 0.5, "ack_sent", clip=clip_id, peer=sender, status="applied"))
    logs[sender].append(line(sender, applied + 0.5 + net_ms, "ack_received", clip=clip_id, peer=receiver,
                             status="applied"))
    return applied - start


def build_logs() -> tuple[dict, dict]:
    logs = {MAC: [], PHONE: [], IPAD: []}
    truth = {}
    truth["text-a"] = clip(logs, PHONE, MAC, 1_000, "0192f3e0-0000-7000-8000-00000000000a", "text", 27, 2.0,
                           detect_ms=300)
    truth["text-b"] = clip(logs, MAC, PHONE, 5_000, "0192f3e0-0000-7000-8000-00000000000b", "text", 4096, 4.5)
    truth["text-c"] = clip(logs, PHONE, MAC, 9_000, "0192f3e0-0000-7000-8000-00000000000c", "text", 120, 60.0)
    truth["image"] = clip(logs, MAC, PHONE, 20_000, "0192f3e0-0000-7000-8000-00000000000d", "image", 5_000_000,
                          1_396.0)
    # The phone forwards the Mac's text clip to an iPad (QC6); the iPad is 2 hops away from the Mac.
    fwd = "0192f3e0-0000-7000-8000-00000000000e"
    truth["forward"] = clip(logs, MAC, PHONE, 30_000, fwd, "text", 50, 3.0)
    logs[PHONE].append(line(PHONE, 30_010, "clip_sent", clip=fwd, peer=IPAD))
    logs[IPAD].append(line(IPAD, 30_014, "clip_received", clip=fwd, peer=PHONE, kind="text", bytes=50))
    logs[IPAD].append(line(IPAD, 30_016, "clip_applied", clip=fwd))
    logs[IPAD].append(line(IPAD, 30_016.5, "ack_sent", clip=fwd, peer=PHONE, status="applied"))
    logs[PHONE].append(line(PHONE, 30_020.5, "ack_received", clip=fwd, peer=IPAD, status="applied"))
    truth["forward-ipad"] = 30_016 - 30_000
    # Reconnects on the Mac: its own Wi-Fi switch, then the phone's, then a pong timeout without trigger.
    for true_ms, ev, fields in [(0, "state", {"to": "Discovering"}), (400, "state", {"to": "Connected", "channel": "lan"}),
                                (40_000, "net", {"change": "down"}), (40_100, "state", {"from": "Connected", "to": "Backoff"}),
                                (41_900, "net", {"change": "up"}), (42_000, "state", {"to": "Discovering"}),
                                (43_150, "state", {"to": "Connected", "channel": "lan"}),
                                (60_000, "state", {"from": "Connected", "to": "Backoff"}),
                                (64_700, "state", {"to": "Connected", "channel": "lan"}),
                                (80_000, "state", {"from": "Connected", "to": "Backoff"}),
                                (80_900, "state", {"to": "Connected", "channel": "lan"})]:
        logs[MAC].append(line(MAC, true_ms, ev, **fields))
    logs[PHONE].append(line(PHONE, 62_500, "net", change="up"))
    truth["reconnect"] = [(43_150 - 41_900), (64_700 - 62_500), None]
    # A clip the Mac refused (conflict, QC8): read and sent, never applied.
    lost = "0192f3e0-0000-7000-8000-00000000000f"
    logs[PHONE].append(line(PHONE, 50_000, "clip_read", clip=lost, kind="text", bytes=10, source="manual"))
    logs[PHONE].append(line(PHONE, 50_001, "clip_sent", clip=lost, peer=MAC))
    logs[PHONE].append(line(PHONE, 50_008, "ack_received", clip=lost, peer=MAC, status="ignored"))
    logs[PHONE].append("HLBENCH/1 wall=nope dev=x role=android ev=clip_read")  # malformed: reported, not fatal
    logs[MAC].append("an unrelated log line")
    return logs, truth


class Harness:
    def __init__(self) -> None:
        self.passed, self.failed = 0, []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
        else:
            self.failed.append(name)
            print(f"  FAIL {name}{': ' + detail if detail else ''}")


def close(a: float | None, b: float | None, tol: float = 0.01) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def run(argv: list[str], main) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def main() -> int:
    t = Harness()
    try:
        parse_line("HLBENCH/1 wall=1 dev=a role=android ev=clip_read clip=x kind=text")
        t.check("clip_read without bytes is rejected", False)
    except ValueError as exc:
        t.check("clip_read without bytes is rejected", "bytes" in str(exc), str(exc))
    t.check("nearest-rank percentile", percentile([5, 1, 3, 2, 4], 95) == 5 and percentile([5, 1, 3, 2, 4], 50) == 3)

    logs, truth = build_logs()
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for dev, lines in logs.items():
            path = Path(tmp) / f"{ROLE[dev]}.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            paths.append(path)
        log = load(paths)
        t.check("malformed line reported, not fatal", len(log.problems) == 1 and "android.log" in log.problems[0],
                str(log.problems))
        found = exchanges(log)
        t.check("one exchange per acknowledged hop", len(found) == 6, str(len(found)))
        clocks = ClockModel(found)
        off = clocks.offset(MAC, PHONE, T0 + 5_000)
        t.check("phone offset found from the exchanges", close(off.value, SKEW[PHONE]) and off.method == "exchange",
                str(off))
        chained = clocks.offset(MAC, IPAD, T0 + 30_000)
        t.check("iPad offset chained through the phone", close(chained.value, SKEW[IPAD]) and chained.method == "chain",
                str(chained))

        items = {x.clip[-1]: x for x in clip_latency.transfers(log, clocks) if x.receiver != IPAD}
        t.check("text a latency", close(items["a"].latency_ms, truth["text-a"]), str(items["a"]))
        t.check("text a detection kept apart", close(items["a"].detect_ms, 300.0), str(items["a"].detect_ms))
        t.check("text b latency", close(items["b"].latency_ms, truth["text-b"]), str(items["b"]))
        t.check("image latency", close(items["d"].latency_ms, truth["image"]), str(items["d"]))
        t.check("breakdown adds up", close(items["a"].sender_local_ms + items["a"].network_ms
                                           + items["a"].receiver_local_ms, items["a"].latency_ms))
        ipad = [x for x in clip_latency.transfers(log, clocks) if x.receiver == IPAD]
        t.check("forwarded clip measured from the Mac to the iPad",
                len(ipad) == 1 and ipad[0].hops == 2 and close(ipad[0].latency_ms, truth["forward-ipad"]), str(ipad))

        missing = clip_latency.unapplied(log, clip_latency.transfers(log, clocks))
        t.check("refused clip listed as not applied", len(missing) == 1 and "ignored" in missing[0], str(missing))
        code, text = run([str(p) for p in paths] + ["--check"], clip_latency.main)
        t.check("text target missed by the 63.5 ms clip fails --check", code == 1 and "FAIL" in text, text)
        code, text = run([str(p) for p in paths] + ["--json"], clip_latency.main)
        report = json.loads(text)
        buckets = {r["bucket"]: r for r in report["summary"]}
        t.check("JSON summary has the text and 5 MB image buckets",
                buckets["text inline"]["count"] == 4 and buckets["image ≈ 5 MB"]["result"] == "PASS", str(buckets))

        eps = reconnect_time.episodes(log, clocks)
        got = [e.reconnect_ms for e in eps]
        t.check("three reconnect episodes", len(eps) == 3, str(eps))
        t.check("Mac Wi-Fi switch", close(got[0], truth["reconnect"][0]) and eps[0].trigger == f"net up on {MAC}",
                str(eps[0]))
        t.check("phone Wi-Fi switch on the Mac's clock", close(got[1], truth["reconnect"][1]), str(eps[1]))
        t.check("episode without trigger keeps only the time since the loss",
                got[2] is None and close(eps[2].since_loss_ms, 900.0), str(eps[2]))
        code, text = run([str(p) for p in paths] + ["--check"], reconnect_time.main)
        t.check("reconnect target met", code == 0 and "PASS" in text, text)

        manual = ClockModel([], {(MAC, PHONE): 1000.0})
        t.check("manual offset used without exchanges", manual.offset(PHONE, MAC, T0).value == -1000.0)
        t.check("no data: offset assumed 0", ClockModel([]).offset(MAC, PHONE, T0).method == "assumed 0")
    sms_self_test.run_checks(t, line, run, close, MAC, PHONE, IPAD)
    print(f"bench self-test: {t.passed} passed, {len(t.failed)} failed")
    return 1 if t.failed else 0


if __name__ == "__main__":
    sys.exit(main())
