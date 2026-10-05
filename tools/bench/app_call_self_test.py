"""App calls (CALL-05) for call_self_test.py: added to the same synthetic session, so their taps sit beside the
cellular ones and must stay out of the cellular action rows.

P rings on the Mac over the LAN, is answered directly from the panel (the panel is shown twice, timed once) and
ended; R reaches the Mac over the relay and is declined; T is answered through the tap-to-answer notification
(counted, not timed); U is answered on the phone and its in-call notification is dismissed (`end=unknown`, no
intent); V is ended from the Mac but the listener is lost before the app's change (`end=unknown`, not timed).
"""

from __future__ import annotations

import app_call_latency

APP_CALL = {k: f"0192f3f2-{n:04x}-7c2d-8e3f-4a5b6c7d8e90" for n, k in enumerate("PRTUV", start=1)}


def change(s, t, call, state, **extra) -> None:
    s.add(s.phone, t + 1, "app_call_changed", call=call, state=state, os=s.wall(s.phone, t), **extra)


def deliver(s, t_os, call, state, via="lan", after=6.0, net=4.0, reason="change", lost=False) -> float:
    """app_call_sent then app_call_received on the Mac; returns the true OS event → received time."""
    s.envs += 1
    e = f"0192f3f3-{s.envs:04x}-7d3e-8f4a-5b6c7d8e9f01"
    s.add(s.phone, t_os + after, "app_call_sent", call=call, env=e, peer=s.mac, via=via, state=state, reason=reason)
    if not lost:
        s.add(s.mac, t_os + after + net, "app_call_received", call=call, env=e, peer=s.phone, state=state)
    return after + net


def act(s, t, call, action, mode, app_ms, state, end=None, net=3.0) -> tuple[float, float]:
    """A tap on the Mac, the phone's intent, the app's change after app_ms and its copy back on the Mac.
    Returns (intent → change on the phone, tap → change received on the Mac)."""
    s.envs += 1
    e = f"0192f3f4-{s.envs:04x}-7d3e-8f4a-5b6c7d8e9f01"
    sent = t + 4
    s.add(s.mac, t, "call_action_tap", call=call, action=action, **{"from": "panel"})
    s.add(s.mac, sent, "call_action_sent", call=call, env=e, peer=s.phone, action=action, via="lan", attempt=1)
    s.add(s.phone, sent + net, "call_action_received", call=call, env=e, peer=s.mac, action=action)
    intent = sent + net + 5
    s.add(s.phone, intent, "app_call_intent_sent", call=call, action=action, mode=mode)
    s.add(s.phone, intent + 1, "call_action_ack_sent", call=call, env=e, peer=s.mac, ok="true")
    s.add(s.mac, intent + 1 + net, "call_action_ack_received", call=call, env=e, peer=s.phone, ok="true")
    change(s, intent + app_ms, call, state, **({"end": end} if end else {}))
    back = deliver(s, intent + app_ms, call, state)
    return app_ms, intent + app_ms + back - t


def build(s) -> dict:
    truth = {"delivery": {}, "shown": {}, "intents": {}, "back": {}, "actions": 0}
    p = APP_CALL["P"]
    change(s, 200_000, p, "ringing")
    truth["delivery"][(p, "ringing")] = deliver(s, 200_000, p, "ringing")
    s.add(s.mac, 200_150, "app_call_panel_shown", call=p)
    truth["shown"][p] = 150.0
    deliver(s, 200_500, p, "ringing", reason="session")  # a new session gets the current version: not measured
    intent, back = act(s, 202_000, p, "answer", "direct", 600.0, "ongoing")
    truth["intents"][(p, "answer")], truth["back"][(p, "answer")] = intent, back
    s.add(s.mac, 202_700, "app_call_panel_shown", call=p)  # the in-call panel: shown again, not timed again
    intent, back = act(s, 210_000, p, "end", "plain", 120.0, "ended", end="ended")
    truth["intents"][(p, "end")], truth["back"][(p, "end")] = intent, back

    r = APP_CALL["R"]
    change(s, 220_000, r, "ringing")
    truth["delivery"][(r, "ringing")] = deliver(s, 220_000, r, "ringing", via="relay", after=10.0, net=300.0)
    s.add(s.mac, 220_380, "app_call_panel_shown", call=r)
    truth["shown"][r] = 380.0
    intent, back = act(s, 221_000, r, "reject", "plain", 200.0, "ended", end="declined")
    truth["intents"][(r, "reject")], truth["back"][(r, "reject")] = intent, back

    t = APP_CALL["T"]
    change(s, 230_000, t, "ringing")
    deliver(s, 230_000, t, "ringing")
    act(s, 231_000, t, "answer", "tap", 3_000.0, "ongoing")  # the user's tap on the phone came 3 s later

    u = APP_CALL["U"]
    change(s, 240_000, u, "ringing")
    deliver(s, 240_000, u, "ringing")
    change(s, 241_000, u, "ongoing")
    deliver(s, 241_000, u, "ongoing")
    change(s, 245_000, u, "ended", end="unknown")  # the in-call notification was dismissed
    deliver(s, 245_000, u, "ended", lost=True)

    v = APP_CALL["V"]
    change(s, 250_000, v, "ongoing")
    deliver(s, 250_000, v, "ongoing")
    act(s, 251_000, v, "end", "plain", 90.0, "ended", end="unknown")  # the listener was lost first
    truth["actions"] = 5  # taps on the Mac: P answer and end, R reject, T answer, V end
    return truth


def check(t, s, log, clocks, close, truth, cellular_actions) -> None:
    t.check("no app call tap in the cellular actions, no phone=?",
            all(a.call not in APP_CALL.values() and a.phone != "?" for a in cellular_actions),
            str([(a.call[:13], a.phone) for a in cellular_actions]))
    states = {(d.call, d.state): d for d in app_call_latency.deliveries(log, clocks) if d.state == "ringing"}
    t.check("app call delivery on the phone's clock, LAN and relay",
            all(close(states[k].latency_ms, want) for k, want in truth["delivery"].items())
            and states[(APP_CALL["R"], "ringing")].via == "relay", str(states))
    t.check("app_call_sent reason=session not measured",
            sum(d.call == APP_CALL["P"] and d.state == "ringing" for d in app_call_latency.deliveries(log, clocks))
            == 1)
    t.check("the lost app call copy is listed", [x for x in app_call_latency.undelivered(log)
                                                if APP_CALL["U"] in x and "ended" in x] != [],
            str(app_call_latency.undelivered(log)))
    views = {v.call: v for v in app_call_latency.shown(log, clocks)}
    t.check("app call panel timed once per call from the first ringing",
            len(app_call_latency.shown(log, clocks)) == len(truth["shown"])
            and all(close(views[c].latency_ms, want) for c, want in truth["shown"].items()), str(views))
    intents = app_call_latency.intents(log)
    timed = {(i.call, i.action): i.latency_ms for i in intents if i.latency_ms is not None}
    t.check("decline, end and direct answer timed on the phone",
            set(timed) == set(truth["intents"]) and all(close(timed[k], v) for k, v in truth["intents"].items()),
            str(timed))
    t.check("a detached end (end=unknown, no intent) is in no action row",
            all(i.call != APP_CALL["U"] for i in intents)
            and next(i for i in intents if i.call == APP_CALL["V"]).latency_ms is None, str(intents))
    t.check("tap to answer counted", app_call_latency.tap_answer_count(intents) == 1)
    acts = {(a.call, a.action): a for a in app_call_latency.actions(log)}
    t.check("app call taps: phone, mode, ack and the result back on the Mac",
            len(acts) == truth["actions"] and all(a.phone == s.phone and a.ok == "true" for a in acts.values())
            and acts[(APP_CALL["T"], "answer")].mode == "tap"
            and all(close(acts[k].to_client_ms, v) for k, v in truth["back"].items()), str(acts))


def check_summary(t, rows: dict) -> None:
    want = {"app call delivery lan": 200.0, "app call delivery relay": 1000.0, "app call shown": 400.0,
            "app call decline": 500.0, "app call end": 500.0, "app call answer direct": 1000.0}
    t.check("app call rows with their targets, all met",
            all(k in rows and rows[k]["target_ms"] == v and rows[k]["result"] == "PASS" for k, v in want.items()),
            str({k: rows.get(k) for k in want}))
    t.check("app call answer tap counted, not timed", rows.get("app call answer tap", {}).get("count") == 1
            and rows["app call answer tap"]["median_ms"] is None, str(rows.get("app call answer tap")))
    back = {k: rows.get(f"app call {k} back", {}) for k in ("answer", "decline", "end")}
    t.check("app call back rows without a target, only taps the phone's intent answered",
            all(r.get("count") == 1 and r.get("target_ms") is None for r in back.values()), str(back))
