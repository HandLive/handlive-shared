"""Reconnect time from the HLBENCH/1 logs (CONN-02: connected again < 3 s after the Wi-Fi changes; gate G1).

    python3 tools/bench/reconnect_time.py mac.log android.log [--offset A:B=MS] [--json] [--check]

An episode runs on a client (Mac, iPhone, iPad) from a `state` event that leaves Connected to the next one that
enters Connected (00-common-specs 0.11). Its trigger is the last `net` event with change=up or changed, or the
last `wake` event, on any device inside the episode — times of other devices are put on the client's clock
(clock_sync.py). Reconnect time = Connected minus trigger; without a trigger (the phone's service restarted,
the pong timed out) only the time since the loss is shown. Target: under 3000 ms on the 95th percentile.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_log import Event, Log, load, local_interval_ms, percentile  # noqa: E402
from clip_latency import parse_offsets  # noqa: E402
from clock_sync import ClockModel, exchanges  # noqa: E402

TARGET_MS = 3000.0
CONNECTED = "Connected"
CLIENT_ROLES = ("macos", "ios")


@dataclass
class Episode:
    client: str
    lost_state: str  # first state after Connected (Backoff, Idle, Discovering…)
    trigger: str  # "net up on <dev>", "wake on <dev>" or "loss"
    reconnect_ms: float | None  # Connected minus trigger
    since_loss_ms: float  # Connected minus the loss
    channel: str  # channel of the new session when the app logs it (lan, relay, usb)


def episodes(log: Log, clocks: ClockModel) -> list[Episode]:
    out = []
    clients = sorted({e.dev for e in log.events if e.ev == "state" and e.role in CLIENT_ROLES})
    triggers = [e for e in log.events if (e.ev == "net" and e.get("change") in ("up", "changed")) or e.ev == "wake"]
    for client in clients:
        states = [e for e in log.events if e.dev == client and e.ev == "state"]
        lost: Event | None = None
        up_since: Event | None = None  # the Connected state that the loss ends
        for e in states:
            if e.get("to") == CONNECTED:
                if lost is not None:
                    out.append(_episode(client, up_since, lost, e, triggers, clocks))
                lost, up_since = None, e
            elif up_since is not None and lost is None:
                lost = e
    return out


def _episode(client: str, up_since: Event, lost: Event, connected: Event, triggers: list[Event],
             clocks: ClockModel) -> Episode:
    since_loss = local_interval_ms(lost, connected)
    best, best_on_client = None, None
    for t in triggers:
        on_client = t.wall_ms if t.dev == client else clocks.to_ref(t.wall_ms, t.dev, client)[0]
        # After the previous connection came up: a Wi-Fi switch is often seen before the session notices the loss.
        if up_since.wall_ms < on_client <= connected.wall_ms and (best is None or on_client > best_on_client):
            best, best_on_client = t, on_client
    if best is None:
        trigger, reconnect = "loss", None
    else:
        what = "wake" if best.ev == "wake" else f"net {best.get('change')}"
        trigger = f"{what} on {best.dev}"
        reconnect = (local_interval_ms(best, connected) if best.dev == client
                     else connected.wall_ms - best_on_client)
    return Episode(client, lost.get("to"), trigger, reconnect, since_loss, connected.get("channel", "?"))


def summarize(items: list[Episode]) -> dict | None:
    values = [e.reconnect_ms for e in items if e.reconnect_ms is not None]
    if not values:
        return None
    p95 = percentile(values, 95)
    return {"count": len(values), "median_ms": percentile(values, 50), "p95_ms": p95, "max_ms": max(values),
            "target_ms": TARGET_MS, "result": "PASS" if p95 < TARGET_MS else "FAIL"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("logs", nargs="+", type=Path, help="log files of every device of the session")
    parser.add_argument("--offset", action="append", default=[], metavar="A:B=MS",
                        help="clock of device B minus clock of A, when the logs hold no request/ack exchange")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    parser.add_argument("--check", action="store_true", help="exit 1 if the target is missed or nothing measured")
    args = parser.parse_args(argv)
    log = load(args.logs)
    clocks = ClockModel(exchanges(log), parse_offsets(args.offset))
    items = episodes(log, clocks)
    summary = summarize(items)
    if args.json:
        print(json.dumps({"episodes": [asdict(e) for e in items], "summary": summary, "skipped": log.problems},
                         indent=2, ensure_ascii=False))
    else:
        for problem in log.problems:
            print(f"skipped {problem}")
        print(f"{'client':9} {'lost to':12} {'trigger':22} {'reconnect':>9} {'since loss':>10}  channel")
        for e in items:
            reconnect = "—" if e.reconnect_ms is None else f"{e.reconnect_ms:.0f}"
            print(f"{e.client:9} {e.lost_state:12} {e.trigger:22} {reconnect:>9} {e.since_loss_ms:>10.0f}  {e.channel}")
        if summary:
            print(f"summary: n={summary['count']} median={summary['median_ms']:.0f} p95={summary['p95_ms']:.0f} "
                  f"max={summary['max_ms']:.0f} ms, target < {TARGET_MS:.0f} → {summary['result']}")
        else:
            print("summary: no episode with a network or wake trigger")
    if args.check and (summary is None or summary["result"] == "FAIL"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
