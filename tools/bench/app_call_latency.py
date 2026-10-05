"""App call latency (CALL-05) from the HLBENCH/1 logs; call_latency.py prints it beside the cellular rows.

Delivery: from the notification event behind a change of the app-call context (`app_call_changed` field `os`) to
the Mac's `app_call_received` of the envelope that carried it (`app_call_sent reason=change`, joined on the envelope
id), on the phone's clock; one change times at most one send per Mac (a send again without a new change, when only
the answer mode or a setting changed, is not timed). Target: under 200 ms on the LAN, 1 s over the relay.
Shown: from the first `app_call_changed state=ringing` of a call to the Mac's `app_call_panel_shown`. Target: 400 ms.
Decline and End: from `app_call_intent_sent action=reject|end` to the next `app_call_changed state=ended` of that
call (`end=declined` or `ended`), phone only. Target: 500 ms for the phone's part alone; CALL-05's 500 ms counts from
the click on the Mac, which the `back` rows below come closer to. Answer direct: from `app_call_intent_sent action=answer
mode=direct` to the next `app_call_changed state=ongoing`, phone only. Target: 1 s. Answer tap (`mode=tap`) waits for
the user's tap on the phone, so it is counted, not timed. Only the first intent of an action before the change it
led to is timed (a resent action sends it again). A call that ends without an intent before it (the listener
lost, the in-call notification dismissed: `end=unknown`) is in no action row.
Tap back on the client: from the Mac's `call_action_tap` of an app call to its `app_call_received` with the resulting
state, one device, no target.
"""

from __future__ import annotations

from dataclasses import dataclass

from bench_log import Event, Log, local_interval_ms
from clock_sync import ClockModel

DELIVERY_TARGET_MS = {"lan": 200.0, "relay": 1000.0}
SHOWN_TARGET_MS = 400.0
INTENT_TARGET_MS = {("reject", "plain"): 500.0, ("end", "plain"): 500.0, ("answer", "direct"): 1000.0}
INTENT_LABEL = {("reject", "plain"): "app call decline", ("end", "plain"): "app call end",
                ("answer", "direct"): "app call answer direct"}
# The state an intent leads to, and the end_reason that says the app did it (CALL-05 API 1 logic 4).
INTENT_RESULT = {"answer": ("ongoing", None), "reject": ("ended", "declined"), "end": ("ended", "ended")}
APP_EVENTS = ("app_call_changed", "app_call_sent", "app_call_received", "app_call_panel_shown",
              "app_call_intent_sent")


@dataclass
class AppDelivery:
    call: str
    env: str
    phone: str
    client: str
    via: str
    state: str
    latency_ms: float  # notification event → received, on the phone's clock
    phone_ms: float  # notification event → envelope handed to the session (phone)
    network_ms: float  # handed over → decrypted on the Mac (across clocks)
    offset_method: str


@dataclass
class AppShown:
    call: str
    client: str
    latency_ms: float  # first ringing event → panel shown, on the phone's clock
    offset_method: str


@dataclass
class AppIntent:
    call: str
    phone: str
    action: str  # answer, reject, end
    mode: str  # direct, tap, plain
    result: str | None  # the state that followed (ongoing, ended) or None
    end: str | None  # its end_reason
    latency_ms: float | None  # intent sent → the app's notification change, phone only; None when not timed
    repeat: bool  # the same action was already sent for this change (a resent call_event/action): not timed


@dataclass
class AppAction:
    call: str
    client: str
    phone: str
    action: str
    source: str
    via: str
    attempts: int
    ok: str | None
    code: str | None
    mode: str | None  # mode of the intent the phone sent for it, None when it sent none
    to_client_ms: float | None  # tap → the resulting app_call_received on this client (one device)
    ack_ms: float | None  # tap → ack received, for an action sent once


def app_call_ids(log: Log) -> set[str]:
    """Call ids that belong to app calls: their taps and acks share the cellular events but not their rows."""
    return {e.get("call") for ev in APP_EVENTS for e in log.of(ev)}


def _changes(log: Log, phone: str, call: str) -> list[Event]:
    return [e for e in log.of("app_call_changed") if e.dev == phone and e.get("call") == call]


def _phone_of(log: Log, call: str) -> str | None:
    return next((e.dev for e in log.of("app_call_changed") if e.get("call") == call), None)


def deliveries(log: Log, clocks: ClockModel) -> list[AppDelivery]:
    received = {(e.dev, e.get("env")): e for e in log.of("app_call_received")}
    out, used = [], set()
    for sent in log.of("app_call_sent"):
        if sent.get("reason") != "change":
            continue  # the current version sent to a new session has no notification event behind it
        causes = [c for c in _changes(log, sent.dev, sent.get("call")) if local_interval_ms(c, sent) >= 0]
        if not causes:
            continue
        # One change times one send per peer: the phone sends the call again with reason=change when only the
        # answer mode or a setting changed (no new notification event), and that send has no start of its own.
        key = (causes[-1].where, sent.get("peer"))
        got = received.get((sent.get("peer"), sent.get("env")))
        if key in used:
            continue
        used.add(key)
        if got is None:
            continue
        os_ms = float(causes[-1].get("os"))
        got_on_phone, offset = clocks.to_ref(got.wall_ms, got.dev, sent.dev)
        out.append(AppDelivery(sent.get("call"), sent.get("env"), sent.dev, got.dev, sent.get("via"),
                               sent.get("state"), got_on_phone - os_ms, sent.wall_ms - os_ms,
                               got_on_phone - sent.wall_ms, offset.method))
    return out


def undelivered(log: Log) -> list[str]:
    received = {(e.dev, e.get("env")) for e in log.of("app_call_received")}
    return [f"{e.get('call')} {e.get('state')} → {e.get('peer')} ({e.get('via')})" for e in log.of("app_call_sent")
            if (e.get("peer"), e.get("env")) not in received]


def shown(log: Log, clocks: ClockModel) -> list[AppShown]:
    out, seen = [], set()
    for e in log.of("app_call_panel_shown"):
        call = e.get("call")
        phone = _phone_of(log, call)
        ring = next((c for c in _changes(log, phone, call) if c.get("state") == "ringing"), None) if phone else None
        if ring is None or (e.dev, call) in seen:
            continue  # a call that never rang (dialed in the app), or the panel shown again for the same call
        seen.add((e.dev, call))
        on_phone, offset = clocks.to_ref(e.wall_ms, e.dev, phone)
        out.append(AppShown(call, e.dev, on_phone - float(ring.get("os")), offset.method))
    return out


def intents(log: Log) -> list[AppIntent]:
    out, seen = [], set()
    for sent in log.of("app_call_intent_sent"):
        call, action, mode = sent.get("call"), sent.get("action"), sent.get("mode")
        wanted, reason = INTENT_RESULT.get(action, (None, None))
        # The first change of the call that settles it after the intent: the wanted state, or the end of the call.
        after = (c for c in _changes(log, sent.dev, call) if local_interval_ms(sent, c) >= 0
                 and c.get("state") in (wanted, "ended"))
        change = next(after, None)
        # Only the first intent of an action before the change it led to: the Mac resends the same envelope after
        # a reconnect and the phone sends the intent again while the notification still offers it.
        key = (sent.dev, call, action, change.where if change else None)
        repeat = key in seen
        seen.add(key)
        hit = change is not None and change.get("state") == wanted and change.get("end") in (None, reason)
        timed = hit and not repeat and (action, mode) in INTENT_TARGET_MS
        out.append(AppIntent(call, sent.dev, action, mode, change.get("state") if change else None,
                             change.get("end") if change else None,
                             float(change.get("os")) - sent.wall_ms if timed else None, repeat))
    return out


def actions(log: Log) -> list[AppAction]:
    ids, out = app_call_ids(log), []
    for tap in log.of("call_action_tap"):
        call, action, client = tap.get("call"), tap.get("action"), tap.dev
        if call not in ids:
            continue
        sent = [e for e in log.of("call_action_sent") if e.dev == client and e.get("call") == call
                and e.get("action") == action and local_interval_ms(tap, e) >= 0]
        env = sent[0].get("env") if sent else None
        phone = sent[0].get("peer") if sent else _phone_of(log, call)
        acks = [e for e in log.of("call_action_ack_received") if e.dev == client and e.get("env") == env]
        got = next((e for e in log.of("call_action_received") if e.dev == phone and e.get("env") == env), None)
        intent = next((e for e in log.of("app_call_intent_sent") if e.dev == phone and e.get("call") == call
                       and e.get("action") == action and local_interval_ms(got, e) >= 0), None) if got else None
        wanted = INTENT_RESULT.get(action, (None, None))[0]
        result = next((e for e in log.of("app_call_received") if e.dev == client and e.get("call") == call
                       and e.get("state") == wanted and local_interval_ms(tap, e) >= 0), None)
        out.append(AppAction(call, client, phone or "?", action, tap.get("from"), sent[0].get("via") if sent else "?",
                             len(sent), acks[0].get("ok") if acks else None,
                             next((e.get("code") for e in acks if e.get("code")), None),
                             intent.get("mode") if intent else None,
                             local_interval_ms(tap, result) if result else None,
                             local_interval_ms(tap, acks[0]) if acks and len(sent) == 1 else None))
    return out


def summary_rows(states: list[AppDelivery], views: list[AppShown], sent: list[AppIntent],
                 acts: list[AppAction]) -> list[tuple[str, list[float], float | None]]:
    """(metric, values, target) of every app call row; the tap-to-answer count is apart (tap_answer_count)."""
    rows = [(f"app call delivery {via}", [d.latency_ms for d in states if d.via == via], target)
            for via, target in DELIVERY_TARGET_MS.items()]
    rows.append(("app call shown", [s.latency_ms for s in views], SHOWN_TARGET_MS))
    rows += [(INTENT_LABEL[key], [i.latency_ms for i in sent if (i.action, i.mode) == key
                                  and i.latency_ms is not None], target) for key, target in INTENT_TARGET_MS.items()]
    # Tap → result on the Mac, only when the phone's intent led to it (timed above): an answer through the
    # tap-to-answer notification waits for the user, and a call that ended otherwise (end=unknown) is not the tap's.
    timed = {(i.call, i.action) for i in sent if i.latency_ms is not None}
    rows += [(f"app call {label} back", [a.to_client_ms for a in acts if a.action == action
                                         and (a.call, action) in timed and a.to_client_ms is not None], None)
             for action, label in (("answer", "answer"), ("reject", "decline"), ("end", "end"))]
    return rows


def tap_answer_count(sent: list[AppIntent]) -> int:
    return sum(i.action == "answer" and i.mode == "tap" and not i.repeat for i in sent)


def print_report(states: list[AppDelivery], views: list[AppShown], sent: list[AppIntent], acts: list[AppAction],
                 log: Log, fmt) -> None:
    for text in undelivered(log):
        print(f"app call never received: {text}")
    if states:
        print(f"{'app call':36} {'phone→client':17} {'via':5} {'state':8} {'latency':>8} {'phone':>6} {'net':>6}  clock")
    for d in states:
        print(f"{d.call:36} {d.phone + '→' + d.client:17} {d.via:5} {d.state:8} {fmt(d.latency_ms):>8} "
              f"{fmt(d.phone_ms):>6} {fmt(d.network_ms):>6}  {d.offset_method}")
    for s in views:
        print(f"app call panel {s.call} on {s.client}: {fmt(s.latency_ms)} ms after ringing ({s.offset_method})")
    for i in sent:
        result = (i.result or "nothing") + (f" end={i.end}" if i.end else "") + (" (repeat)" if i.repeat else "")
        print(f"app call intent {i.action} mode={i.mode} {i.call} on {i.phone}: {result}, {fmt(i.latency_ms)} ms")
    if acts:
        print(f"{'action':7} {'app call':36} {'client':8} {'from':12} {'via':5} {'tries':>5} {'ok':5} {'mode':6} "
              f"{'→client':>8} {'ack':>6}  error")
    for a in acts:
        print(f"{a.action:7} {a.call:36} {a.client:8} {a.source:12} {a.via:5} {a.attempts:>5} {a.ok or '—':5} "
              f"{a.mode or '—':6} {fmt(a.to_client_ms):>8} {fmt(a.ack_ms):>6}  {a.code or ''}")
