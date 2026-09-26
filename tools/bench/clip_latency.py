"""Clipboard latency from the HLBENCH/1 logs of both devices (04-clipboard QC9, Phase 1 gate G1).

    python3 tools/bench/clip_latency.py android.log mac.log [--offset 8c7d6e5f:5b1f8c2e=1234.5] [--json] [--check]

Latency of one clip = the receiver's `clip_applied` minus the sender's `clip_read`, with the receiver's time put
on the sender's clock (clock_sync.py). Copy detection is not part of it (QC9) and is shown apart. Targets:
text sent inline (plaintext up to CLIP_INLINE_MAX) under 50 ms, images of about 5 MB under 2 s — on the 95th
percentile. --check exits 1 when a target is missed or nothing was measured.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_log import Log, load, local_interval_ms, percentile  # noqa: E402
from clock_sync import ClockModel, exchanges  # noqa: E402

CLIP_INLINE_MAX = 180 * 1024  # 04-clipboard QC5
DETECT_WINDOW_MS = 5_000  # a copy_detected this close before clip_read belongs to it
# (label, kind, lowest bytes, highest bytes, target ms or None)
BUCKETS = [
    ("text inline", "text", 0, CLIP_INLINE_MAX, 50.0),
    ("text chunked", "text", CLIP_INLINE_MAX + 1, math.inf, None),
    ("image < 4.5 MB", "image", 0, 4_499_999, None),
    ("image ≈ 5 MB", "image", 4_500_000, 5_500_000, 2000.0),
    ("image > 5.5 MB", "image", 5_500_001, math.inf, None),
]


@dataclass
class Transfer:
    clip: str
    kind: str
    bytes: int
    source: str
    sender: str
    receiver: str
    hops: int  # 1 direct, 2 forwarded by the phone (QC6)
    latency_ms: float
    detect_ms: float | None  # copy detection before the read (not part of the latency)
    sender_local_ms: float | None  # clip_read -> clip_sent on the sender
    receiver_local_ms: float | None  # clip_received -> clip_applied on the receiver
    network_ms: float | None  # the rest: encryption, network, decryption
    offset_ms: float
    offset_error_ms: float
    offset_method: str


def transfers(log: Log, clocks: ClockModel) -> list[Transfer]:
    by = {}
    for e in log.events:
        if "clip" in e.fields:
            by.setdefault((e.ev, e.dev, e.get("clip")), e)
    out = []
    for (ev, sender, clip), read in sorted(by.items(), key=lambda item: item[1].wall_ms):
        if ev != "clip_read":
            continue
        detect = _detected_before(log, read)
        for (ev2, receiver, clip2), applied in by.items():
            if ev2 != "clip_applied" or clip2 != clip or receiver == sender:
                continue
            received = by.get(("clip_received", receiver, clip))
            via = received.get("peer") if received else None
            applied_on_sender, offset = clocks.to_ref(applied.wall_ms, receiver, sender)
            latency = applied_on_sender - read.wall_ms
            sent = by.get(("clip_sent", sender, clip)) if via in (None, sender) else None
            sender_local = local_interval_ms(read, sent) if sent else None
            receiver_local = local_interval_ms(received, applied) if received and via == sender else None
            network = (latency - sender_local - receiver_local
                       if sender_local is not None and receiver_local is not None else None)
            out.append(Transfer(clip, read.get("kind"), int(read.get("bytes")), read.get("source", "?"), sender,
                                receiver, 1 if via in (None, sender) else 2, latency,
                                local_interval_ms(detect, read) if detect else None, sender_local, receiver_local,
                                network, offset.value, offset.error, offset.method))
    return out


def _detected_before(log: Log, read) -> object | None:
    candidates = [e for e in log.events if e.ev == "copy_detected" and e.dev == read.dev
                  and 0 <= local_interval_ms(e, read) <= DETECT_WINDOW_MS]
    return candidates[-1] if candidates else None


def unapplied(log: Log, items: list[Transfer]) -> list[str]:
    """Clips read and sent that no device applied: lost, refused (ack status) or the receiver's log is missing."""
    done = {t.clip for t in items}
    out = []
    for read in log.of("clip_read"):
        clip = read.get("clip")
        if clip in done:
            continue
        acks = [f"{e.get('peer')}: {e.get('status')}" for e in log.of("ack_received") if e.get("clip") == clip]
        sent = [e.get("peer") for e in log.of("clip_sent") if e.get("clip") == clip]
        out.append(f"{clip} ({read.get('kind')}, {read.get('bytes')} bytes) sent to {', '.join(sent) or 'nobody'}; "
                   f"acks: {', '.join(acks) or 'none'}")
    return out


def summarize(items: list[Transfer]) -> list[dict]:
    rows = []
    for label, kind, low, high, target in BUCKETS:
        values = [t.latency_ms for t in items if t.kind == kind and low <= t.bytes <= high and t.hops == 1]
        if not values:
            continue
        p95 = percentile(values, 95)
        rows.append({"bucket": label, "count": len(values), "median_ms": percentile(values, 50), "p95_ms": p95,
                     "max_ms": max(values), "target_ms": target,
                     "result": None if target is None else ("PASS" if p95 < target else "FAIL")})
    return rows


def parse_offsets(values: list[str]) -> dict[tuple[str, str], float]:
    """--offset A:B=MS means the clock of B minus the clock of A is MS milliseconds."""
    out = {}
    for value in values:
        pair, _, ms = value.partition("=")
        a, _, b = pair.partition(":")
        if not (a and b and ms):
            raise SystemExit(f"--offset {value!r}: expected DEV_A:DEV_B=MS")
        out[(a, b)] = float(ms)
    return out


def _fmt(value: float | None) -> str:
    return "—" if value is None or math.isnan(value) else f"{value:.1f}"


def print_report(items: list[Transfer], rows: list[dict], log: Log) -> None:
    for problem in log.problems:
        print(f"skipped {problem}")
    for text in unapplied(log, items):
        print(f"not applied: {text}")
    print(f"{'clip':36}  {'kind':5} {'bytes':>9}  {'sender→receiver':17} {'hops':>4} {'latency':>8} "
          f"{'detect':>7} {'send':>6} {'net':>6} {'recv':>6}  clock offset receiver-sender")
    for t in items:
        print(f"{t.clip:36}  {t.kind:5} {t.bytes:>9}  {t.sender + '→' + t.receiver:17} {t.hops:>4} "
              f"{_fmt(t.latency_ms):>8} {_fmt(t.detect_ms):>7} {_fmt(t.sender_local_ms):>6} {_fmt(t.network_ms):>6} "
              f"{_fmt(t.receiver_local_ms):>6}  {_fmt(t.offset_ms)} ±{_fmt(t.offset_error_ms)} ({t.offset_method})")
    print("summary (direct transfers, ms)")
    for r in rows:
        target = f"target < {r['target_ms']:.0f} → {r['result']}" if r["target_ms"] else "no target"
        print(f"  {r['bucket']:15} n={r['count']:<4} median={r['median_ms']:.1f} p95={r['p95_ms']:.1f} "
              f"max={r['max_ms']:.1f}  {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("logs", nargs="+", type=Path, help="log files of every device of the session")
    parser.add_argument("--offset", action="append", default=[], metavar="A:B=MS",
                        help="clock of device B minus clock of A, when the logs hold no request/ack exchange")
    parser.add_argument("--window-s", type=float, default=120.0, help="how far to look for an exchange (s)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if a target is missed or no bucket with a target was measured")
    args = parser.parse_args(argv)
    log = load(args.logs)
    clocks = ClockModel(exchanges(log), parse_offsets(args.offset), args.window_s * 1000)
    items = transfers(log, clocks)
    rows = summarize(items)
    if args.json:
        print(json.dumps({"transfers": [_finite(asdict(t)) for t in items], "summary": rows,
                          "not_applied": unapplied(log, items), "skipped": log.problems}, indent=2, ensure_ascii=False))
    else:
        print_report(items, rows, log)
    targeted = [r for r in rows if r["target_ms"] is not None]
    if args.check and (not targeted or any(r["result"] == "FAIL" for r in targeted)):
        return 1
    return 0


def _finite(row: dict) -> dict:
    """JSON has no NaN: an unknown offset error becomes null."""
    return {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in row.items()}


if __name__ == "__main__":
    sys.exit(main())
