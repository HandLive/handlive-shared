"""Tests of sms_latency.py and of the sms/send clock exchanges on synthetic logs with known timings.

Run through self_test.py (CI). The logs hold no clipboard event: the clock offsets must come from the sms/send
acks alone (the phone runs 1234.5 ms ahead of the Mac, the iPad 250 ms behind the true time).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import sms_latency
from bench_log import load
from clock_sync import ClockModel, exchanges

MSG = {n: f"sms:{n}" for n in range(100, 106)}


def reply(logs, line, client, phone, start, local, via, radio_ms, net_ms=3.0, result="sent", retry=False):
    """Log one reply; returns the true time from the tap to the confirmed status (None when it fails)."""
    logs[client] += [line(client, start, "sms_send_tap", local=local),
                     line(client, start + 40, "sms_bubble", local=local),
                     line(client, start + 50, "sms_send_sent", local=local, peer=phone, attempt=1, via=via)]
    sent_at = start + 50
    if retry:  # the first attempt got no ack: sent again with the same envelope id
        sent_at = start + 5_050
        logs[client].append(line(client, sent_at, "sms_send_sent", local=local, peer=phone, attempt=2, via=via))
    got = sent_at + net_ms
    logs[phone] += [line(phone, got, "sms_send_received", local=local, peer=client),
                    line(phone, got + 7, "sms_send_ack_sent", local=local, peer=client, ok="true"),
                    line(phone, got + 9, "sms_status_sent", local=local, peer=client, status="sending")]
    logs[client] += [line(client, got + 7 + net_ms, "sms_send_ack_received", local=local, peer=phone, ok="true"),
                     line(client, got + 9 + net_ms, "sms_status_received", local=local, status="sending")]
    done = got + 7 + radio_ms
    extra = {"code": "SMS_NO_SERVICE"} if result == "failed" else {}
    logs[phone] += [line(phone, done, "sms_radio_done", local=local, result=result, **extra),
                    line(phone, done + 1, "sms_status_sent", local=local, peer=client, status=result, **extra)]
    logs[client].append(line(client, done + 1 + net_ms, "sms_status_received", local=local, status=result, **extra))
    return None if result == "failed" else done + 1 + net_ms - start


def incoming(logs, line, phone, client, start, msg, via, network_ms, client_ms, notify=True, box="inbox"):
    """Log one new message sent to a client; returns the true onchange → notified latency."""
    wall_change = line(phone, start, "wake").split(" wall=")[1].split(" ")[0]  # the phone's wall clock at start
    logs[phone] += [line(phone, start + 110, "sms_detected", msg=msg, box=box, onchange=wall_change),
                    line(phone, start + 115, "sms_new_sent", msg=msg, peer=client, via=via)]
    logs[client].append(line(client, start + 115 + network_ms, "sms_new_received", msg=msg, peer=phone))
    if notify:
        logs[client].append(line(client, start + 115 + network_ms + client_ms, "sms_notified", msg=msg))
    return 115 + network_ms + client_ms


def run_checks(t, line, run, close, mac, phone, ipad) -> None:
    logs = {mac: [], phone: [], ipad: []}
    truth = {"sent": {}}
    truth["sent"]["a"] = reply(logs, line, mac, phone, 1_000, "0192f3e2-0000-7000-8000-00000000000a", "lan", 830)
    reply(logs, line, mac, phone, 5_000, "0192f3e2-0000-7000-8000-00000000000b", "lan", 480, result="failed",
          retry=True)
    truth["sent"]["c"] = reply(logs, line, mac, phone, 20_000, "0192f3e2-0000-7000-8000-00000000000c", "relay",
                               1_300, net_ms=80.0)
    truth["sent"]["d"] = reply(logs, line, ipad, phone, 25_000, "0192f3e2-0000-7000-8000-00000000000d", "lan", 600)
    note = {100: incoming(logs, line, phone, mac, 30_000, MSG[100], "lan", 15, 30),
            101: incoming(logs, line, phone, mac, 40_000, MSG[101], "lan", 185, 120),
            102: incoming(logs, line, phone, mac, 50_000, MSG[102], "relay", 590, 45)}
    incoming(logs, line, phone, mac, 55_000, MSG[103], "lan", 10, 0, notify=False)  # conversation open on the Mac
    incoming(logs, line, phone, mac, 56_000, MSG[104], "lan", 10, 0, notify=False, box="sent")  # sent from the phone
    wall_change = line(phone, 60_000, "wake").split(" wall=")[1].split(" ")[0]
    logs[phone] += [line(phone, 60_110, "sms_detected", msg=MSG[105], box="inbox", onchange=wall_change),
                    line(phone, 60_300, "sms_push_sent", msg=MSG[105], peer=ipad)]
    logs[ipad].append(line(ipad, 61_000, "sms_push_shown", msg=MSG[105]))

    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for dev, lines in logs.items():
            path = Path(tmp) / f"sms-{dev}.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            paths.append(path)
        log = load(paths)
        t.check("sms logs parse", not log.problems, str(log.problems))
        found = exchanges(log)
        t.check("sms/send acks give the exchanges, the retried send is left out",
                sorted(x.ref[-1] for x in found) == ["a", "c", "d"], str([x.ref for x in found]))
        clocks = ClockModel(found)
        off = clocks.offset(mac, phone, 1_727_151_100_000.0 + 1_000)
        t.check("phone offset from the sms/send exchanges", close(off.value, 1234.5) and off.method == "exchange",
                str(off))

        notes = {n.msg: n for n in sms_latency.notifications(log, clocks)}
        t.check("three notifications measured", sorted(notes) == [MSG[100], MSG[101], MSG[102]], str(sorted(notes)))
        for n in (100, 101, 102):
            t.check(f"notification {n} latency", close(notes[MSG[n]].latency_ms, note[n]), str(notes[MSG[n]]))
        first = notes[MSG[100]]
        t.check("notification breakdown adds up", close(first.detect_ms + first.phone_ms + first.network_ms
                                                        + first.client_ms, first.latency_ms), str(first))
        t.check("relay notification bucketed apart", notes[MSG[102]].via == "relay")
        missing = sms_latency.not_notified(log, list(notes.values()))
        t.check("only the incoming message without a notification is listed", missing == [f"{MSG[103]} → {mac} (lan)"],
                str(missing))

        items = {s.local[-1]: s for s in sms_latency.sends(log)}
        for key in ("a", "c", "d"):
            t.check(f"reply {key} confirmed as sent", close(items[key].sent_ms, truth["sent"][key]), str(items[key]))
        t.check("failed reply: status, error code, two attempts, no sent time",
                items["b"].result == "failed" and items["b"].error == "SMS_NO_SERVICE" and items["b"].attempts == 2
                and items["b"].sent_ms is None, str(items["b"]))
        t.check("bubble and ack measured on the client", close(items["a"].bubble_ms, 40.0)
                and close(items["a"].ack_ms, 63.0), str(items["a"]))
        t.check("radio time on the phone", close(items["a"].radio_ms, 830.0), str(items["a"]))

        shown = sms_latency.pushes(log, clocks)
        t.check("push shown on the iPad, offset chained through the phone",
                len(shown) == 1 and close(shown[0].latency_ms, 1000.0), str(shown))

        code, text = run([str(p) for p in paths] + ["--check", "--json"], sms_latency.main)
        rows = {r["metric"]: r for r in json.loads(text)["summary"]}
        t.check("summary: every target met", code == 0 and all(r["result"] in (None, "PASS") for r in rows.values())
                and rows["notification lan"]["count"] == 2 and rows["reply sent"]["count"] == 3, text[:600])
        t.check("p95 of the replies", close(rows["reply sent"]["p95_ms"], max(truth["sent"].values())), str(rows))

        slow = [line(phone, 70_000 + 110, "sms_detected", msg="sms:106", box="inbox",
                     onchange=line(phone, 70_000, "wake").split(" wall=")[1].split(" ")[0]),
                line(phone, 70_115, "sms_new_sent", msg="sms:106", peer=mac, via="lan")]
        with paths[1].open("a", encoding="utf-8") as fh:
            fh.write("\n".join(slow) + "\n")
        with paths[0].open("a", encoding="utf-8") as fh:
            fh.write(line(mac, 70_720, "sms_notified", msg="sms:106") + "\n")
        code, text = run([str(p) for p in paths] + ["--check"], sms_latency.main)
        t.check("a 720 ms notification on the LAN fails --check", code == 1 and "notification lan" in text
                and "FAIL" in text, text[-400:])
