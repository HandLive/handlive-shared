"""Tests of call_latency.py and of the call_event/action clock exchanges on synthetic logs with known timings.

Run through self_test.py (CI). The logs hold no clipboard or SMS event: the clock offsets must come from the
call_event/action acks alone (the phone runs 1234.5 ms ahead of the Mac, the iPad 250 ms behind the true time).
Calls: A rings on the Mac (number after the first RINGING), is answered and ended from the panel; B is declined from
the panel; C rings during a Focus on the Mac, reaches the iPad over the relay with a banner, and is missed; D rings
while the iPad has no session (push), and is declined from the notification over the relay; F is dialed on the
phone and gets a waiting call.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import call_latency
from bench_log import load
from clock_sync import ClockModel, exchanges

CALL = {k: f"0192f3f0-{n:04x}-7c2d-8e3f-4a5b6c7d8e90" for n, k in enumerate("ABCDFGH", start=1)}


def env(n: int) -> str:
    return f"0192f3f1-{n:04x}-7d3e-8f4a-5b6c7d8e9f01"


class Session:
    """Builds the three logs and remembers the true latencies."""

    def __init__(self, line, mac, phone, ipad) -> None:
        self.line, self.mac, self.phone, self.ipad = line, mac, phone, ipad
        self.logs = {mac: [], phone: [], ipad: []}
        self.envs = 0
        self.delivery: dict[str, float] = {}  # envelope id → OS callback to received

    def add(self, dev, t, ev, **fields) -> None:
        self.logs[dev].append(self.line(dev, t, ev, **fields))

    def wall(self, dev, t) -> str:
        return self.line(dev, t, "wake").split(" wall=")[1].split(" ")[0]

    def change(self, t, call, state, trigger="listener", waiting="false", **extra) -> None:
        self.add(self.phone, t + 1, "call_changed", call=call, state=state, waiting=waiting, trigger=trigger,
                 os=self.wall(self.phone, t), **extra)

    def deliver(self, t_os, call, state, to, via="lan", after=8.0, net=3.0, lost=False) -> None:
        self.envs += 1
        e = env(self.envs)
        self.add(self.phone, t_os + after, "call_state_sent", call=call, env=e, peer=to, via=via, state=state,
                 reason="change")
        if not lost:
            self.add(to, t_os + after + net, "call_state_received", call=call, env=e, peer=self.phone, state=state)
            self.delivery[e] = after + net

    def act(self, client, t, call, action, source, via="lan", net=3.0, telecom_ms=150.0, result=None,
            state_after=10.0, connect_ms=0.0) -> tuple[float, float]:
        """An action from tap to the resulting state on the client; returns (tap → phone callback, tap → client).
        connect_ms: an iPhone woken by a notification action connects before it can send (CALL-02 B2)."""
        self.envs += 1
        e = env(self.envs)
        sent = t + 4 + connect_ms
        self.add(client, t, "call_action_tap", call=call, action=action, **{"from": source})
        self.add(client, sent, "call_action_sent", call=call, env=e, peer=self.phone, action=action, via=via,
                 attempt=1)
        self.add(self.phone, sent + net, "call_action_received", call=call, env=e, peer=client, action=action)
        self.add(self.phone, sent + net + 8, "call_action_ack_sent", call=call, env=e, peer=client, ok="true")
        self.add(client, sent + 2 * net + 8, "call_action_ack_received", call=call, env=e, peer=self.phone, ok="true")
        state = call_latency.ACTION_STATE[action]
        t_os = sent + net + 8 + telecom_ms
        self.change(t_os, call, state, **({"end": result} if result else {}))
        self.deliver(t_os, call, state, client, via=via, after=state_after, net=net)
        return t_os - t, t_os + state_after + net - t


def build(line, mac, phone, ipad):
    s = Session(line, mac, phone, ipad)
    truth = {"shown": {}, "actions": {}}
    # A: rings on the Mac, the number arrives 40 ms later (CALL-01 E10), answered then ended from the panel.
    s.change(1000, CALL["A"], "ringing", number="none", sub=1)
    s.deliver(1000, CALL["A"], "ringing", mac)
    s.add(mac, 1015, "call_alert", call=CALL["A"], focus="off", panel="true", ring="true", level="passive")
    s.add(mac, 1120, "call_panel_shown", call=CALL["A"])
    s.add(mac, 1125, "call_notified", call=CALL["A"], level="passive")
    truth["shown"][("panel", CALL["A"])] = 120.0
    s.change(1040, CALL["A"], "ringing", trigger="broadcast", number="known", sub=1)
    s.deliver(1040, CALL["A"], "ringing", mac)
    truth["actions"][("answer", CALL["A"])] = s.act(mac, 3000, CALL["A"], "answer", "panel")
    truth["actions"][("end", CALL["A"])] = s.act(mac, 9000, CALL["A"], "end", "panel", telecom_ms=80.0,
                                                 result="ended")
    # B: declined from the panel; its number came before the RINGING callback.
    s.change(20000, CALL["B"], "ringing", number="known")
    s.deliver(20000, CALL["B"], "ringing", mac)
    s.add(mac, 20012, "call_alert", call=CALL["B"], focus="unknown", panel="true", ring="false", level="passive")
    s.add(mac, 20090, "call_panel_shown", call=CALL["B"])
    truth["shown"][("panel", CALL["B"])] = 90.0
    truth["actions"][("reject", CALL["B"])] = s.act(mac, 21000, CALL["B"], "reject", "panel", telecom_ms=70.0,
                                                    result="rejected")
    # C: a Focus is on on the Mac (notification only); the iPad has a session over the relay; missed.
    s.change(30000, CALL["C"], "ringing", number="known")
    s.deliver(30000, CALL["C"], "ringing", mac)
    s.deliver(30000, CALL["C"], "ringing", ipad, via="relay", after=10.0, net=290.0)
    s.add(mac, 30014, "call_alert", call=CALL["C"], focus="on", panel="false", ring="false", level="time_sensitive")
    s.add(mac, 30020, "call_notified", call=CALL["C"], level="time_sensitive")
    s.add(ipad, 30250, "call_banner_shown", call=CALL["C"])
    truth["shown"][("banner", CALL["C"])] = 250.0
    s.change(55000, CALL["C"], "idle", end="missed")
    s.deliver(55000, CALL["C"], "idle", mac)
    s.add(mac, 55900, "call_missed_notified", call=CALL["C"], source="log_new", entry=5120)
    truth["missed"] = 900.0
    # D: the iPad has no session: push once the number is known, then Decline from the notification over the relay.
    s.change(60000, CALL["D"], "ringing", number="none")
    s.change(60120, CALL["D"], "ringing", trigger="broadcast", number="known")
    s.add(phone, 60300, "call_push_sent", call=CALL["D"], peer=ipad, reason="call_incoming", status=202)
    s.add(ipad, 61100, "call_push_shown", call=CALL["D"], reason="call_incoming", late="false")
    truth["push"] = (180.0, 1100.0)
    truth["actions"][("reject", CALL["D"])] = s.act(ipad, 64000, CALL["D"], "reject", "notification", via="relay",
                                                    net=60.0, telecom_ms=22.0, result="rejected", connect_ms=900.0)
    # F: dialed on the phone, then a call waits (CALL-01 E9): information only, never pushed; the copy for the iPad is
    # lost, and the waiting call is declined on the phone.
    s.change(70000, CALL["F"], "offhook")
    s.deliver(70000, CALL["F"], "offhook", mac)
    s.change(75000, CALL["F"], "ringing", waiting="true")
    s.deliver(75000, CALL["F"], "ringing", mac, after=6.0, net=5.0)
    s.deliver(75000, CALL["F"], "ringing", ipad, via="relay", lost=True)
    s.change(80000, CALL["F"], "offhook")
    s.deliver(80000, CALL["F"], "offhook", mac)
    return s, truth


def run_checks(t, line, run, close, mac, phone, ipad) -> None:
    s, truth = build(line, mac, phone, ipad)
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for dev, lines in s.logs.items():
            path = Path(tmp) / f"call-{dev}.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            paths.append(path)
        log = load(paths)
        t.check("call logs parse", not log.problems, str(log.problems))
        found = exchanges(log)
        t.check("call_event/action acks give the clock exchanges", len(found) == 4, str([x.ref for x in found]))
        clocks = ClockModel(found)
        off = clocks.offset(mac, phone, 1_727_151_100_000.0 + 3_000)
        t.check("phone offset from the call actions", close(off.value, 1234.5) and off.method == "exchange", str(off))

        states = call_latency.deliveries(log, clocks)
        t.check("every received state measured", len(states) == len(s.delivery), f"{len(states)} of {len(s.delivery)}")
        t.check("state latency from the OS callback", all(close(d.latency_ms, s.delivery[d.env]) for d in states),
                str([(d.env[-4:], d.latency_ms, s.delivery[d.env]) for d in states]))
        first = next(d for d in states if d.call == CALL["A"])
        t.check("state breakdown adds up", close(first.phone_ms + first.network_ms, first.latency_ms), str(first))
        t.check("the number broadcast counts from its own arrival",
                sum(d.call == CALL["A"] and d.trigger == "broadcast" for d in states) == 1)
        t.check("relay copies bucketed apart", [d.via for d in states if d.client == ipad] == ["relay", "relay"])
        lost = call_latency.undelivered(log)
        t.check("the lost waiting-call copy is listed", len(lost) == 1 and CALL["F"] in lost[0], str(lost))

        views = {(v.kind, v.call): v for v in call_latency.shown(log, clocks)}
        t.check("panel and banner times", set(views) == set(truth["shown"]) and all(
            close(views[k].latency_ms, want) for k, want in truth["shown"].items()), str(views))

        acts = {(a.action, a.call): a for a in call_latency.actions(log, clocks)}
        for key, (to_phone, to_client) in truth["actions"].items():
            a = acts.get(key)
            t.check(f"{key[0]} of {key[1][9:13]}: tap to the phone and back",
                    a is not None and close(a.to_phone_ms, to_phone) and close(a.to_client_ms, to_client), str(a))
        d = acts[("reject", CALL["D"])]
        t.check("decline from the iPad notification over the relay, offset of the iPad",
                d.source == "notification" and d.via == "relay" and d.ok == "true", str(d))

        missed = call_latency.missed(log, clocks)
        t.check("missed-call notification after the call ended", len(missed) == 1
                and close(missed[0].latency_ms, truth["missed"]), str(missed))
        pushes = call_latency.pushes(log, clocks)
        t.check("push answered after the number, shown by the extension",
                len(pushes) == 1 and close(pushes[0].after_number_ms, truth["push"][0])
                and close(pushes[0].shown_ms, truth["push"][1]), str(pushes))
        t.check("Focus rule kept", call_latency.alert_problems(log) == [], str(call_latency.alert_problems(log)))

        code, text = run([str(p) for p in paths] + ["--check", "--json"], call_latency.main)
        report = json.loads(text)
        rows = {r["metric"]: r for r in report["summary"]}
        t.check("summary: every target met", code == 0 and all(r["result"] in (None, "PASS") for r in rows.values())
                and rows["state lan"]["count"] == len(s.delivery) - 2 and rows["state relay"]["count"] == 2,
                text[:600])
        t.check("summary rows of every metric", {"shown panel", "shown banner", "answer to phone offhook",
                                                 "answer back on client", "decline back on client",
                                                 "end back on client", "decline from notification",
                                                 "missed notification", "incoming push", "push shown"} <= set(rows),
                str(sorted(rows)))
        t.check("p95 of the panel", close(rows["shown panel"]["p95_ms"], 120.0), str(rows["shown panel"]))

        with paths[0].open("a", encoding="utf-8") as fh:
            fh.write(line(mac, 90_000, "call_alert", call=CALL["G"], focus="on", panel="true", ring="false",
                          level="time_sensitive") + "\n")
        code, text = run([str(p) for p in paths] + ["--check"], call_latency.main)
        t.check("a panel during a Focus fails --check", code == 1 and "Focus rule broken" in text, text[-400:])

        slow = Session(line, mac, phone, ipad)
        slow.change(95_000, CALL["H"], "ringing", number="known")
        with paths[1].open("a", encoding="utf-8") as fh:
            fh.write("\n".join(slow.logs[phone]) + "\n")
        with paths[0].open("a", encoding="utf-8") as fh:
            fh.write(line(mac, 95_450, "call_panel_shown", call=CALL["H"]) + "\n")
        log = load(paths)
        views = call_latency.shown(log, ClockModel(exchanges(log)))
        rows = {r["metric"]: r for r in call_latency.summarize([], views, [], [], [])}
        t.check("a 450 ms panel fails the 300 ms target", rows["shown panel"]["result"] == "FAIL", str(rows))
