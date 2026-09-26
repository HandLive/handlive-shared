"""SMS latency from the HLBENCH/1 logs of the phone and its clients (Phase 2 targets).

    python3 tools/bench/sms_latency.py android.log mac.log [ipad.log] [--offset A:B=MS] [--json] [--check]

New SMS notification (SMS-02): from the phone's ContentObserver call (`sms_detected` field `onchange`, the moment the
provider was written) to the client's `sms_notified`, the client's time put on the phone's clock (clock_sync.py).
Only incoming messages (box = inbox) notify. Target: under 500 ms on the LAN, 1 s over the relay (SMS-02).

Reply confirmed as Sent (SMS-04): from the client's `sms_send_tap` to its `sms_status_received` with status = sent —
one device, so no clock offset is involved. Target: under 2 s. Also shown with their SMS-04 targets: the placeholder
bubble (100 ms) and the ack on the LAN (300 ms).

Push to an iPhone/iPad without a session (CONN-04): `onchange` to the extension's `sms_push_shown`; no target.
A target is met when the 95th percentile is under it; --check exits 1 when one is missed or nothing with a target
was measured.
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
from bench_log import Event, Log, load, local_interval_ms, percentile  # noqa: E402
from clip_latency import parse_offsets  # noqa: E402
from clock_sync import ClockModel, exchanges  # noqa: E402

NOTIFY_TARGET_MS = {"lan": 500.0, "relay": 1000.0}
SENT_TARGET_MS = 2000.0
BUBBLE_TARGET_MS = 100.0
ACK_LAN_TARGET_MS = 300.0


@dataclass
class Notification:
    msg: str
    phone: str
    client: str
    via: str  # lan or relay, from the phone's sms_new_sent
    latency_ms: float  # onchange → sms_notified
    detect_ms: float  # onchange → sms_detected (phone)
    phone_ms: float | None  # sms_detected → sms_new_sent (phone)
    network_ms: float | None  # sms_new_sent → sms_new_received (across clocks)
    client_ms: float | None  # sms_new_received → sms_notified (client)
    offset_ms: float
    offset_error_ms: float
    offset_method: str


@dataclass
class Send:
    local: str
    client: str
    phone: str
    via: str
    attempts: int
    result: str  # sent, delivered, failed or pending (no final status)
    sent_ms: float | None  # tap → status sent (the target)
    bubble_ms: float | None  # tap → placeholder bubble
    ack_ms: float | None  # tap → ack received, for a request sent once (a retry measures the wait, not the ack)
    radio_ms: float | None  # phone: ack sent → every part reported
    error: str | None


@dataclass
class Push:
    msg: str
    phone: str
    device: str
    latency_ms: float  # onchange → sms_push_shown
    offset_method: str


def _first(events: list[Event]) -> Event | None:
    return events[0] if events else None


def notifications(log: Log, clocks: ClockModel) -> list[Notification]:
    detected = {}
    for e in log.of("sms_detected"):
        if e.get("box") == "inbox":
            detected.setdefault(e.get("msg"), e)
    out = []
    for done in log.of("sms_notified"):
        msg, client = done.get("msg"), done.dev
        det = detected.get(msg)
        if det is None:
            continue
        phone = det.dev
        start = float(det.get("onchange"))
        sent = _first([e for e in log.of("sms_new_sent") if e.dev == phone and e.get("msg") == msg
                       and e.get("peer") == client])
        received = _first([e for e in log.of("sms_new_received") if e.dev == client and e.get("msg") == msg])
        done_on_phone, offset = clocks.to_ref(done.wall_ms, client, phone)
        received_on_phone = clocks.to_ref(received.wall_ms, client, phone)[0] if received else None
        out.append(Notification(
            msg, phone, client, sent.get("via") if sent else "?", done_on_phone - start, det.wall_ms - start,
            local_interval_ms(det, sent) if sent else None,
            received_on_phone - sent.wall_ms if sent and received else None,
            local_interval_ms(received, done) if received else None,
            offset.value, offset.error, offset.method))
    return out


def not_notified(log: Log, items: list[Notification]) -> list[str]:
    """Incoming messages the phone sent to a client that never notified (setting off, conversation open, lost)."""
    done = {(n.msg, n.client) for n in items}
    inbox = {e.get("msg") for e in log.of("sms_detected") if e.get("box") == "inbox"}
    return [f"{e.get('msg')} → {e.get('peer')} ({e.get('via')})" for e in log.of("sms_new_sent")
            if e.get("msg") in inbox and (e.get("msg"), e.get("peer")) not in done]


def sends(log: Log) -> list[Send]:
    out = []
    for tap in log.of("sms_send_tap"):
        local, client = tap.get("local"), tap.dev

        def mine(ev: str, dev: str | None = None) -> list[Event]:
            return [e for e in log.of(ev) if e.get("local") == local and (dev is None or e.dev == dev)]

        sent = mine("sms_send_sent", client)
        statuses = mine("sms_status_received", client)
        acks = mine("sms_send_ack_received", client)
        bubble = _first(mine("sms_bubble", client))
        phone = sent[0].get("peer") if sent else "?"
        ack_sent = _first(mine("sms_send_ack_sent", phone))
        radio = _first(mine("sms_radio_done", phone))
        final = next((s for s in statuses if s.get("status") in ("sent", "delivered", "failed")), None)
        confirmed = _first([s for s in statuses if s.get("status") in ("sent", "delivered")])
        result = final.get("status") if final else "pending"
        error = next((e.get("code") for e in acks + statuses if e.get("code")), None)
        out.append(Send(local, client, phone, sent[0].get("via") if sent else "?", len(sent), result,
                        local_interval_ms(tap, confirmed) if confirmed else None,
                        local_interval_ms(tap, bubble) if bubble else None,
                        local_interval_ms(tap, acks[0]) if acks and len(sent) == 1 else None,
                        local_interval_ms(ack_sent, radio) if ack_sent and radio else None, error))
    return out


def pushes(log: Log, clocks: ClockModel) -> list[Push]:
    detected = {e.get("msg"): e for e in log.of("sms_detected")}
    out = []
    for shown in log.of("sms_push_shown"):
        det = detected.get(shown.get("msg"))
        if det is None:
            continue
        on_phone, offset = clocks.to_ref(shown.wall_ms, shown.dev, det.dev)
        out.append(Push(shown.get("msg"), det.dev, shown.dev, on_phone - float(det.get("onchange")), offset.method))
    return out


def _row(label: str, values: list[float], target: float | None) -> dict | None:
    if not values:
        return None
    p95 = percentile(values, 95)
    return {"metric": label, "count": len(values), "median_ms": percentile(values, 50), "p95_ms": p95,
            "max_ms": max(values), "target_ms": target,
            "result": None if target is None else ("PASS" if p95 < target else "FAIL")}


def summarize(notes: list[Notification], items: list[Send], shown: list[Push]) -> list[dict]:
    rows = []
    for via, target in NOTIFY_TARGET_MS.items():
        rows.append(_row(f"notification {via}", [n.latency_ms for n in notes if n.via == via], target))
    rows.append(_row("reply sent", [s.sent_ms for s in items if s.sent_ms is not None], SENT_TARGET_MS))
    rows.append(_row("placeholder bubble", [s.bubble_ms for s in items if s.bubble_ms is not None],
                     BUBBLE_TARGET_MS))
    rows.append(_row("ack lan", [s.ack_ms for s in items if s.ack_ms is not None and s.via == "lan"],
                     ACK_LAN_TARGET_MS))
    rows.append(_row("push shown", [p.latency_ms for p in shown], None))
    return [r for r in rows if r]


def _fmt(value: float | None) -> str:
    return "—" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.1f}"


def print_report(notes: list[Notification], items: list[Send], shown: list[Push], rows: list[dict],
                 log: Log) -> None:
    for problem in log.problems:
        print(f"skipped {problem}")
    for text in not_notified(log, notes):
        print(f"not notified: {text}")
    print(f"{'message':12} {'phone→client':17} {'via':5} {'latency':>8} {'detect':>7} {'phone':>6} {'net':>6} "
          f"{'client':>7}  clock offset client-phone")
    for n in notes:
        print(f"{n.msg:12} {n.phone + '→' + n.client:17} {n.via:5} {_fmt(n.latency_ms):>8} {_fmt(n.detect_ms):>7} "
              f"{_fmt(n.phone_ms):>6} {_fmt(n.network_ms):>6} {_fmt(n.client_ms):>7}  "
              f"{_fmt(n.offset_ms)} ±{_fmt(n.offset_error_ms)} ({n.offset_method})")
    print(f"{'send (local_id)':36} {'client':8} {'via':5} {'tries':>5} {'result':9} {'sent':>7} {'bubble':>7} "
          f"{'ack':>6} {'radio':>7}  error")
    for s in items:
        print(f"{s.local:36} {s.client:8} {s.via:5} {s.attempts:>5} {s.result:9} {_fmt(s.sent_ms):>7} "
              f"{_fmt(s.bubble_ms):>7} {_fmt(s.ack_ms):>6} {_fmt(s.radio_ms):>7}  {s.error or ''}")
    for p in shown:
        print(f"push {p.msg} {p.phone}→{p.device}: {_fmt(p.latency_ms)} ms ({p.offset_method})")
    print("summary (ms)")
    for r in rows:
        target = f"target < {r['target_ms']:.0f} → {r['result']}" if r["target_ms"] else "no target"
        print(f"  {r['metric']:19} n={r['count']:<4} median={r['median_ms']:.1f} p95={r['p95_ms']:.1f} "
              f"max={r['max_ms']:.1f}  {target}")


def _finite(row: dict) -> dict:
    return {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in row.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("logs", nargs="+", type=Path, help="log files of every device of the session")
    parser.add_argument("--offset", action="append", default=[], metavar="A:B=MS",
                        help="clock of device B minus clock of A, when the logs hold no request/ack exchange")
    parser.add_argument("--window-s", type=float, default=120.0, help="how far to look for an exchange (s)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the tables")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if a target is missed or nothing with a target was measured")
    args = parser.parse_args(argv)
    log = load(args.logs)
    clocks = ClockModel(exchanges(log), parse_offsets(args.offset), args.window_s * 1000)
    notes, items, shown = notifications(log, clocks), sends(log), pushes(log, clocks)
    rows = summarize(notes, items, shown)
    if args.json:
        print(json.dumps({"notifications": [_finite(asdict(n)) for n in notes], "sends": [asdict(s) for s in items],
                          "pushes": [asdict(p) for p in shown], "summary": rows,
                          "not_notified": not_notified(log, notes), "skipped": log.problems},
                         indent=2, ensure_ascii=False))
    else:
        print_report(notes, items, shown, rows, log)
    targeted = [r for r in rows if r["target_ms"] is not None]
    if args.check and (not targeted or any(r["result"] == "FAIL" for r in targeted)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
