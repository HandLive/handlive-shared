"""Call latency from the HLBENCH/1 logs of the phone and its clients (Phase 3 targets).

    python3 tools/bench/call_latency.py android.log mac.log [iphone.log] [--offset A:B=MS] [--json] [--check]

State delivery (CALL-01): from the OS callback or broadcast behind a change of the call context (`call_changed`
field `os`) to the client's `call_state_received` of the envelope that carried the change (joined on the envelope
id), the client's time put on the phone's clock (clock_sync.py). Target: under 200 ms on the LAN, 1 s over the relay.
Call shown (CALL-01): from the first RINGING callback of a call to the Mac's `call_panel_shown` or the iPhone/iPad's
`call_banner_shown`. Target: 300 ms.
Answer (CALL-02): from the Mac's `call_action_tap action=answer` to the phone's OFFHOOK callback, across clocks, and
to the Mac's `call_state_received state=offhook`, one device. Target: 500 ms each. Decline and End: tap to the
client's `call_state_received state=idle`, 500 ms (CALL-02, CALL-03).
Decline from an iPhone/iPad notification (CALL-02 B1–B3): from `call_action_tap from=notification` to the phone's
IDLE callback. Target: 2 s (over the relay).
Missed call (CALL-04): from the phone's IDLE callback of a missed call to the client's `call_missed_notified`.
Target: 1.5 s.
Incoming push (CALL-01 API 4): from the moment the number is known — or the end of the 300 ms wait for it — to
`call_push_sent status=202`, phone only, target 300 ms; and from RINGING to the extension's `call_push_shown`, no
target (APNs).
Focus (CALL-01 E4, API 5): every `call_alert` of the Mac follows the rule — Focus on: no panel, no ringtone, a
time-sensitive notification; Focus status not readable: the panel without ringtone; otherwise the panel with a
passive notification — and no panel is shown while a Focus is on.
A target is met when the 95th percentile is under it; --check exits 1 when one is missed, an alert breaks the Focus
rule, or nothing with a target was measured.
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

STATE_TARGET_MS = {"lan": 200.0, "relay": 1000.0}
SHOWN_TARGET_MS = 300.0
ACTION_TARGET_MS = 500.0
NOTIFICATION_DECLINE_TARGET_MS = 2000.0
MISSED_TARGET_MS = 1500.0
PUSH_TARGET_MS = 300.0
NUMBER_WAIT_MS = 300.0  # CALL-01 API 4 logic 2: the phone waits this long after RINGING for the number
# The state each action leads to on the phone (CALL-02, CALL-03).
ACTION_STATE = {"answer": "offhook", "reject": "idle", "end": "idle"}


@dataclass
class Delivery:
    call: str
    env: str
    phone: str
    client: str
    via: str
    state: str
    trigger: str
    latency_ms: float  # OS callback → state received, on the phone's clock
    phone_ms: float  # OS callback → envelope handed to the session (phone)
    network_ms: float  # handed over → decrypted on the client (across clocks)
    offset_method: str


@dataclass
class Shown:
    call: str
    client: str
    kind: str  # panel (Mac) or banner (iPhone/iPad)
    latency_ms: float  # first RINGING callback → shown, on the phone's clock
    offset_method: str


@dataclass
class Action:
    call: str
    client: str
    phone: str
    action: str
    source: str  # panel, menu, banner, notification
    via: str
    attempts: int
    ok: str | None  # "true", "false" or None without an ack
    code: str | None
    to_phone_ms: float | None  # tap → the phone's OFFHOOK or IDLE callback (across clocks)
    to_client_ms: float | None  # tap → the resulting state received on this client (one device)
    ack_ms: float | None  # tap → ack received, for an action sent once


@dataclass
class Missed:
    call: str
    client: str
    source: str  # log_new or state
    latency_ms: float  # the phone's IDLE callback → missed-call notification, on the phone's clock


@dataclass
class Push:
    call: str
    phone: str
    device: str
    reason: str
    status: str
    after_number_ms: float | None  # number known (or the wait over) → push answered, phone only (call_incoming)
    shown_ms: float | None  # first RINGING callback → shown by the extension (call_incoming)


def _changes(log: Log, phone: str, call: str) -> list[Event]:
    return [e for e in log.of("call_changed") if e.dev == phone and e.get("call") == call]


def _first_ringing(log: Log, phone: str, call: str) -> Event | None:
    return next((e for e in _changes(log, phone, call) if e.get("state") == "ringing"
                 and e.get("waiting") == "false"), None)


def _phone_of(log: Log, call: str) -> str | None:
    return next((e.dev for e in log.of("call_changed") if e.get("call") == call), None)


def _after(events: list[Event], start: Event) -> list[Event]:
    """Events of start's device that come after it (monotonic clock when both have it)."""
    return [e for e in events if e.dev == start.dev and local_interval_ms(start, e) >= 0]


def deliveries(log: Log, clocks: ClockModel) -> list[Delivery]:
    received = {(e.dev, e.get("env")): e for e in log.of("call_state_received")}
    out = []
    for sent in log.of("call_state_sent"):
        if sent.get("reason") != "change":
            continue  # the current state sent to a new session (CALL-01 E8) has no OS callback behind it
        causes = [c for c in _changes(log, sent.dev, sent.get("call")) if local_interval_ms(c, sent) >= 0]
        got = received.get((sent.get("peer"), sent.get("env")))
        if not causes or got is None:
            continue
        cause = causes[-1]
        os_ms = float(cause.get("os"))
        got_on_phone, offset = clocks.to_ref(got.wall_ms, got.dev, sent.dev)
        out.append(Delivery(sent.get("call"), sent.get("env"), sent.dev, got.dev, sent.get("via"), sent.get("state"),
                            cause.get("trigger"), got_on_phone - os_ms, sent.wall_ms - os_ms,
                            got_on_phone - sent.wall_ms, offset.method))
    return out


def undelivered(log: Log) -> list[str]:
    received = {(e.dev, e.get("env")) for e in log.of("call_state_received")}
    return [f"{e.get('call')} {e.get('state')} → {e.get('peer')} ({e.get('via')})" for e in log.of("call_state_sent")
            if (e.get("peer"), e.get("env")) not in received]


def shown(log: Log, clocks: ClockModel) -> list[Shown]:
    out = []
    for ev, kind in (("call_panel_shown", "panel"), ("call_banner_shown", "banner")):
        for e in log.of(ev):
            phone = _phone_of(log, e.get("call"))
            ring = _first_ringing(log, phone, e.get("call")) if phone else None
            if ring is None:
                continue
            on_phone, offset = clocks.to_ref(e.wall_ms, e.dev, phone)
            out.append(Shown(e.get("call"), e.dev, kind, on_phone - float(ring.get("os")), offset.method))
    return out


def actions(log: Log, clocks: ClockModel) -> list[Action]:
    out = []
    for tap in log.of("call_action_tap"):
        call, action, client = tap.get("call"), tap.get("action"), tap.dev
        sent = [e for e in _after(log.of("call_action_sent"), tap) if e.get("call") == call
                and e.get("action") == action]
        env = sent[0].get("env") if sent else None
        phone = sent[0].get("peer") if sent else _phone_of(log, call)
        acks = [e for e in log.of("call_action_ack_received") if e.dev == client and e.get("env") == env]
        wanted = ACTION_STATE.get(action)
        result = next((e for e in _after(log.of("call_state_received"), tap) if e.get("call") == call
                       and e.get("state") == wanted), None)
        got = next((e for e in log.of("call_action_received") if e.dev == phone and e.get("env") == env), None)
        on_phone = next((e for e in _after(_changes(log, phone, call), got) if e.get("state") == wanted), None) \
            if got else None
        to_phone = None
        if on_phone is not None:
            tap_on_phone, _ = clocks.to_ref(tap.wall_ms, client, phone)
            to_phone = float(on_phone.get("os")) - tap_on_phone
        out.append(Action(call, client, phone or "?", action, tap.get("from"), sent[0].get("via") if sent else "?",
                          len(sent), acks[0].get("ok") if acks else None,
                          next((e.get("code") for e in acks if e.get("code")), None), to_phone,
                          local_interval_ms(tap, result) if result else None,
                          local_interval_ms(tap, acks[0]) if acks and len(sent) == 1 else None))
    return out


def missed(log: Log, clocks: ClockModel) -> list[Missed]:
    out = []
    for e in log.of("call_missed_notified"):
        phone = _phone_of(log, e.get("call"))
        idle = next((c for c in _changes(log, phone, e.get("call")) if c.get("state") == "idle"
                     and c.get("end") == "missed"), None) if phone else None
        if idle is None:
            continue
        on_phone, _ = clocks.to_ref(e.wall_ms, e.dev, phone)
        out.append(Missed(e.get("call"), e.dev, e.get("source"), on_phone - float(idle.get("os"))))
    return out


def pushes(log: Log, clocks: ClockModel) -> list[Push]:
    out = []
    for sent in log.of("call_push_sent"):
        call, reason = sent.get("call"), sent.get("reason")
        ring = _first_ringing(log, sent.dev, call)
        after_number = shown_ms = None
        if reason == "call_incoming" and ring is not None:
            ring_os = float(ring.get("os"))
            known = next((float(c.get("os")) for c in _changes(log, sent.dev, call) if c.get("number") == "known"), None)
            start = known if known is not None and known <= ring_os + NUMBER_WAIT_MS else ring_os + NUMBER_WAIT_MS
            after_number = sent.wall_ms - start if sent.get("status") == "202" else None
            display = next((e for e in log.of("call_push_shown") if e.dev == sent.get("peer")
                            and e.get("call") == call and e.get("reason") == reason), None)
            if display is not None:
                shown_ms = clocks.to_ref(display.wall_ms, display.dev, sent.dev)[0] - ring_os
        out.append(Push(call, sent.dev, sent.get("peer"), reason, sent.get("status"), after_number, shown_ms))
    return out


def alert_problems(log: Log) -> list[str]:
    """Mac alerts that break the Focus rule of CALL-01 E4 and API 5."""
    rule = {"on": ("false", "false", "time_sensitive"), "unknown": ("true", "false", "passive")}
    problems, focused = [], set()
    for e in log.of("call_alert"):
        focus, got = e.get("focus"), (e.get("panel"), e.get("ring"), e.get("level"))
        if focus == "on":
            focused.add((e.dev, e.get("call")))
        want = rule.get(focus)
        if want and got != want:
            problems.append(f"{e.get('call')} on {e.dev}: Focus {focus} gave panel={got[0]} ring={got[1]} "
                            f"level={got[2]}, expected panel={want[0]} ring={want[1]} level={want[2]}")
        if focus == "off" and e.get("panel") == "true" and e.get("level") != "passive":
            problems.append(f"{e.get('call')} on {e.dev}: a panel with a {e.get('level')} notification (two alert layers)")
    problems += [f"{e.get('call')} on {e.dev}: panel shown while a Focus is on" for e in log.of("call_panel_shown")
                 if (e.dev, e.get("call")) in focused]
    return problems


def _row(label: str, values: list[float], target: float | None) -> dict | None:
    if not values:
        return None
    p95 = percentile(values, 95)
    return {"metric": label, "count": len(values), "median_ms": percentile(values, 50), "p95_ms": p95,
            "max_ms": max(values), "target_ms": target,
            "result": None if target is None else ("PASS" if p95 < target else "FAIL")}


def summarize(states: list[Delivery], views: list[Shown], acts: list[Action], lost: list[Missed],
              sent: list[Push]) -> list[dict]:
    rows = [_row(f"state {via}", [d.latency_ms for d in states if d.via == via], target)
            for via, target in STATE_TARGET_MS.items()]
    rows += [_row(f"shown {kind}", [s.latency_ms for s in views if s.kind == kind], SHOWN_TARGET_MS)
             for kind in ("panel", "banner")]
    local = [a for a in acts if a.source != "notification"]
    rows.append(_row("answer to phone offhook", [a.to_phone_ms for a in local if a.action == "answer"
                                                 and a.to_phone_ms is not None], ACTION_TARGET_MS))
    for action, label in (("answer", "answer back on client"), ("reject", "decline back on client"),
                          ("end", "end back on client")):
        rows.append(_row(label, [a.to_client_ms for a in local if a.action == action and a.to_client_ms is not None],
                         ACTION_TARGET_MS))
    rows.append(_row("decline from notification", [a.to_phone_ms for a in acts if a.source == "notification"
                                                   and a.action == "reject" and a.to_phone_ms is not None],
                     NOTIFICATION_DECLINE_TARGET_MS))
    rows.append(_row("missed notification", [m.latency_ms for m in lost], MISSED_TARGET_MS))
    rows.append(_row("incoming push", [p.after_number_ms for p in sent if p.after_number_ms is not None],
                     PUSH_TARGET_MS))
    rows.append(_row("push shown", [p.shown_ms for p in sent if p.shown_ms is not None], None))
    return [r for r in rows if r]


def _fmt(value: float | None) -> str:
    return "—" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.1f}"


def print_report(states, views, acts, lost, sent, rows, problems, log: Log) -> None:
    for problem in log.problems:
        print(f"skipped {problem}")
    for text in undelivered(log):
        print(f"state never received: {text}")
    for text in problems:
        print(f"Focus rule broken: {text}")
    print(f"{'call':36} {'phone→client':17} {'via':5} {'state':7} {'trigger':9} {'latency':>8} {'phone':>6} "
          f"{'net':>6}  clock")
    for d in states:
        print(f"{d.call:36} {d.phone + '→' + d.client:17} {d.via:5} {d.state:7} {d.trigger:9} {_fmt(d.latency_ms):>8} "
              f"{_fmt(d.phone_ms):>6} {_fmt(d.network_ms):>6}  {d.offset_method}")
    for s in views:
        print(f"{s.kind} {s.call} on {s.client}: {_fmt(s.latency_ms)} ms after RINGING ({s.offset_method})")
    print(f"{'action':7} {'call':36} {'client':8} {'from':12} {'via':5} {'tries':>5} {'ok':5} {'→phone':>7} "
          f"{'→client':>8} {'ack':>6}  error")
    for a in acts:
        print(f"{a.action:7} {a.call:36} {a.client:8} {a.source:12} {a.via:5} {a.attempts:>5} {a.ok or '—':5} "
              f"{_fmt(a.to_phone_ms):>7} {_fmt(a.to_client_ms):>8} {_fmt(a.ack_ms):>6}  {a.code or ''}")
    for m in lost:
        print(f"missed {m.call} on {m.client} ({m.source}): {_fmt(m.latency_ms)} ms after the call ended")
    for p in sent:
        print(f"push {p.reason} {p.call} {p.phone}→{p.device}: status {p.status}, after number "
              f"{_fmt(p.after_number_ms)} ms, shown {_fmt(p.shown_ms)} ms after RINGING")
    print("summary (ms)")
    for r in rows:
        target = f"target < {r['target_ms']:.0f} → {r['result']}" if r["target_ms"] else "no target"
        print(f"  {r['metric']:25} n={r['count']:<4} median={r['median_ms']:.1f} p95={r['p95_ms']:.1f} "
              f"max={r['max_ms']:.1f}  {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("logs", nargs="+", type=Path, help="log files of every device of the session")
    parser.add_argument("--offset", action="append", default=[], metavar="A:B=MS",
                        help="clock of device B minus clock of A, when the logs hold no request/ack exchange")
    parser.add_argument("--window-s", type=float, default=120.0, help="how far to look for an exchange (s)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the tables")
    parser.add_argument("--check", action="store_true", help="exit 1 if a target is missed, an alert breaks the "
                                                             "Focus rule, or nothing with a target was measured")
    args = parser.parse_args(argv)
    log = load(args.logs)
    clocks = ClockModel(exchanges(log), parse_offsets(args.offset), args.window_s * 1000)
    states, views, acts = deliveries(log, clocks), shown(log, clocks), actions(log, clocks)
    lost, sent, problems = missed(log, clocks), pushes(log, clocks), alert_problems(log)
    rows = summarize(states, views, acts, lost, sent)
    if args.json:
        print(json.dumps({"states": [asdict(d) for d in states], "shown": [asdict(s) for s in views],
                          "actions": [asdict(a) for a in acts], "missed": [asdict(m) for m in lost],
                          "pushes": [asdict(p) for p in sent], "summary": rows, "focus_problems": problems,
                          "undelivered": undelivered(log), "skipped": log.problems}, indent=2, ensure_ascii=False))
    else:
        print_report(states, views, acts, lost, sent, rows, problems, log)
    targeted = [r for r in rows if r["target_ms"] is not None]
    if args.check and (not targeted or problems or any(r["result"] == "FAIL" for r in targeted)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
