"""Scenario `calls`: CALL-01…04 with the emulator's modem as the caller (`adb emu gsm call|cancel`).

A fake contact is inserted so the caller's name can be checked; the Mac answers, declines and ends calls over
WebSocket, which is all a Mac without HFP can do (C12); hold, DTMF and mute must be refused with CALL_HFP_REQUIRED.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import mac_crypto as C
from bench_lines import peer8
from scenario_common import FAKE, features, grant_and_refresh

CALL_PERMISSIONS = ["READ_PHONE_STATE", "READ_CALL_LOG", "ANSWER_PHONE_CALLS", "READ_CONTACTS"]
CONTACT_NAME = "E2E Test Contact"
IDLE_CONTROLS = {"answer": False, "reject": False, "end": False, "hold": "unavailable", "dtmf": "unavailable",
                 "mute": "unavailable"}


def run(ctx) -> None:
    rec, adb = ctx.rec, ctx.adb
    cap = grant_and_refresh(ctx, CALL_PERMISSIONS, "call")
    call = features(cap, "call")
    rec.check("calls in effect: can_answer, can_end, caller_id", "0.7.2, CONN-01 API 7",
              call.get("enabled") and call.get("can_answer") and call.get("can_end") and call.get("caller_id"),
              json.dumps(call))
    adb.delete_contacts_named(CONTACT_NAME)
    adb.insert_contact(CONTACT_NAME, FAKE["contact"])
    s = ctx.session
    if s is None:
        return
    for number in (FAKE["contact"], FAKE["waiting"], FAKE["unknown"]):   # a call left over from an earlier run
        adb.gsm_cancel(number.lstrip("+"))
    call_id = _answered_call(ctx, s)
    if call_id:
        _end(ctx, ctx.session, call_id)
    _rejected_call(ctx, ctx.session)
    _missed_call(ctx, ctx.session)
    _not_found(ctx, ctx.session)
    _log_sync(ctx, ctx.session)
    rec.check("no schema violation in the call messages", "shared/schemas (incl. call_event-state rules)",
              not ctx.session.violations, "; ".join(ctx.session.violations[:3]))
    _bench_report(ctx)


def _states(s, call_id: str | None = None, after: int = 0) -> list:
    return s.collect(lambda m: m.type == "call_event" and m.op == "state"
                     and (call_id is None or m.data["call_id"] == call_id), after)


def _wait_state(s, pred, timeout: float, after: int):
    return s.wait(lambda m: m.type == "call_event" and m.op == "state" and pred(m.data), timeout, after=after)


def _ring(ctx, s, number: str, named: bool) -> tuple[dict | None, float | None, int]:
    """Rings the phone; returns the ringing state that carries the number (and the name), its latency from the
    modem command, and how many ringing versions came before it (E10: the number may come later)."""
    ctx.pause()
    mark = s.mark()
    t0 = time.monotonic()
    ctx.adb.gsm_call(number.lstrip("+"))
    got = _wait_state(s, lambda d: d["state"] == "ringing" and d["number"] == number
                      and (d["display_name"] is not None or not named), 20, mark)
    first = _wait_state(s, lambda d: d["state"] == "ringing", 0.1, mark)
    earlier = len([m for m in _states(s, after=mark) if got and m.index < got.index])
    return (got.data if got else (first.data if first else None),
            (first.mono - t0) * 1000 if first else None, earlier)


def _action(ctx, s, call_id: str, action: str, **extra):
    """call_event/action with the benchmark lines of a Mac click (tools/bench/README.md, call events)."""
    peer = peer8(ctx.client.record.peer_device_id)
    if action in ("answer", "reject", "end"):
        s.bench.line("call_action_tap", call=call_id, action=action, **{"from": "panel"})
    t0 = time.monotonic()
    env_id, ts = s.send("call_event", "action", {"call_id": call_id, "action": action, **extra})
    if action in ("answer", "reject", "end"):
        s.bench.line("call_action_sent", call=call_id, env=env_id, peer=peer, action=action, via="lan", attempt=1)
    ack = s.wait_ack(env_id, ts, t0)
    if ack is not None and action in ("answer", "reject", "end"):
        s.bench.line("call_action_ack_received", call=call_id, env=env_id, peer=peer, ok=ack.ok, code=ack.code)
    return ack, t0


def _err(ack) -> str:
    if ack is None:
        return "no ack within 10 s"
    return f"ok {ack.data}" if ack.ok else f"{ack.code} {ack.error.get('details')}"


def _answered_call(ctx, s) -> str | None:
    rec, adb = ctx.rec, ctx.adb
    number = FAKE["contact"]
    state, ms, earlier = _ring(ctx, s, number, named=True)
    rec.check("ringing call reaches the Mac as call_event/state", "CALL-01 steps 1–4, API 1", state is not None,
              "" if state else "no ringing state in 20 s", latency_ms=ms, target_ms=200)
    if state is None:
        return None
    rec.info("ringing versions before the one with the caller's number", "CALL-01 E10", str(earlier))
    want = {"direction": "incoming", "state": "ringing", "waiting": False, "number": number,
            "display_name": CONTACT_NAME, "presentation": "allowed", "answered_at": None, "ended_at": None,
            "end_reason": None, "hfp_connected": False, "audio_on": "phone",
            "controls": {"answer": True, "reject": True, "end": False, "hold": "unavailable",
                         "dtmf": "unavailable", "mute": "unavailable"}}
    diff = {k: state.get(k) for k, v in want.items() if state.get(k) != v}
    rec.check("ringing state: E.164 number, contact name, controls for a Mac without HFP", "CALL-01 API 1",
              not diff, f"differs: {diff}" if diff else "")
    call_id = state["call_id"]
    ack, _ = _action(ctx, s, call_id, "hold")
    rec.check("hold over WebSocket → CALL_HFP_REQUIRED {action: hold}", "CALL-03 E2, 0.7.1",
              ack is not None and not ack.ok and ack.code == "CALL_HFP_REQUIRED"
              and (ack.error.get("details") or {}).get("action") == "hold", _err(ack))
    ctx.pause()
    mark = s.mark()
    ack, t0 = _action(ctx, s, call_id, "answer", audio="phone")
    rec.check("answer from the Mac: ack {}", "CALL-02 steps 4–6, API 1", ack is not None and ack.ok and ack.data == {},
              _err(ack), latency_ms=ack.latency_ms if ack else None)
    off = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "offhook", 10, mark)
    rec.check("state offhook with answered_at, End allowed", "CALL-02 step 7, CALL-01 API 1 logic 2",
              off is not None and off.data["answered_at"] is not None and off.data["controls"]["end"] is True
              and off.data["controls"]["answer"] is False, json.dumps(off.data["controls"]) if off else "no offhook",
              latency_ms=(off.mono - t0) * 1000 if off else None, target_ms=500)
    phone = adb.call_state()
    rec.check("Android's own call state: offhook with an active foreground call",
              "CALL-02 postcondition (TelecomManager.acceptRingingCall)",
              phone.get("mCallState") == 2 and phone.get("mForegroundCallState") == 1, f"{phone}")
    for action in ("dtmf", "mute", "unhold"):
        ack, _ = _action(ctx, s, call_id, action)
        rec.check(f"{action} over WebSocket → CALL_HFP_REQUIRED", "CALL-03 API 1 logic 1",
                  ack is not None and ack.code == "CALL_HFP_REQUIRED", _err(ack))
    time.sleep(3.2)                                 # past the 3 s action lock (CALL-02 API 1 logic 3)
    ack, _ = _action(ctx, s, call_id, "answer", audio="phone")
    rec.check("answer while offhook → CALL_ACTION_NOT_ALLOWED {state: offhook, reason: state}", "CALL-02 E2",
              ack is not None and not ack.ok and ack.code == "CALL_ACTION_NOT_ALLOWED"
              and (ack.error.get("details") or {}) == {"state": "offhook", "reason": "state"}, _err(ack))
    _reconnect_mid_call(ctx, call_id)
    _waiting(ctx, ctx.session, call_id)
    return call_id


def _waiting(ctx, s, call_id: str) -> None:
    """CALL-01 E9, CALL-03 E7: a second call during the active one is information only over WebSocket."""
    rec, adb = ctx.rec, ctx.adb
    second = FAKE["waiting"]
    ctx.pause()
    mark = s.mark()
    t0 = time.monotonic()
    adb.gsm_call(second.lstrip("+"))
    w = _wait_state(s, lambda d: d["call_id"] == call_id and d["waiting"] is True and d["waiting_number"] == second,
                    20, mark)
    first = _wait_state(s, lambda d: d["call_id"] == call_id and d["waiting"] is True, 0.1, mark)
    phone = adb.call_state()
    if w is None and first is None and phone.get("mRingingCallState", 0) not in (5, 6):
        rec.skip("waiting call", "CALL-01 E9, CALL-03 E7",
                 f"the emulator's modem did not present a second call during the active one (telephony.registry "
                 f"{phone}); nothing reached the phone's listener either")
        adb.gsm_cancel(second.lstrip("+"))
        return
    rec.check("waiting call: same call_id, state ringing, waiting = true, waiting_number", "CALL-01 E9, API 1 logic 2",
              w is not None and w.data["state"] == "ringing" and w.data["number"] == FAKE["contact"]
              and w.data["answered_at"] is not None,
              json.dumps({k: (w or first).data.get(k) for k in ("state", "waiting", "waiting_number")})
              if (w or first) else f"no state; phone {phone}",
              latency_ms=(first.mono - t0) * 1000 if first else None)
    if w:
        rec.check("while waiting every WebSocket control is off", "CALL-01 API 1 controls, CALL-03 E7",
                  w.data["controls"] == IDLE_CONTROLS, json.dumps(w.data["controls"]))
        ack, _ = _action(ctx, s, call_id, "end")
        rec.check("end while a call waits → CALL_ACTION_NOT_ALLOWED {reason: waiting}", "CALL-03 API 1 logic 2",
                  ack is not None and not ack.ok and ack.code == "CALL_ACTION_NOT_ALLOWED"
                  and (ack.error.get("details") or {}).get("reason") == "waiting", _err(ack))
    mark = s.mark()
    adb.gsm_cancel(second.lstrip("+"))
    back = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "offhook" and d["waiting"] is False,
                       15, mark)
    rec.check("the waiting caller hangs up → offhook, waiting = false, first call kept", "CALL-01 API 1 logic 2",
              back is not None and back.data["waiting_number"] is None and back.data["number"] == FAKE["contact"],
              "" if back else "no state back to offhook")


def _reconnect_mid_call(ctx, call_id: str) -> None:
    """CALL-01 E8, API 1 logic 3: a client that connects mid-call gets the current state after capabilities."""
    s = ctx.connect()
    if s is None:
        return
    got = _wait_state(s, lambda d: d["call_id"] == call_id, 5, 0)
    ctx.rec.check("reconnecting mid-call: the new session receives the current state", "CALL-01 E8, API 1 logic 3",
                  got is not None and got.data["state"] == "offhook", "" if got else "no state in 5 s")


def _end(ctx, s, call_id: str) -> None:
    rec, adb = ctx.rec, ctx.adb
    ctx.pause()
    mark = s.mark()
    ack, t0 = _action(ctx, s, call_id, "end")
    rec.check("end from the Mac: ack {}", "CALL-03 steps 6–8, API 1", ack is not None and ack.ok, _err(ack),
              latency_ms=ack.latency_ms if ack else None)
    idle = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "idle", 10, mark)
    rec.check("state idle, end_reason ended, no controls", "CALL-03 step 9, CALL-01 API 1 logic 5",
              idle is not None and idle.data["end_reason"] == "ended" and idle.data["controls"] == IDLE_CONTROLS
              and idle.data["ended_at"] is not None, json.dumps({k: idle.data[k] for k in ("end_reason",)}) if idle
              else "no idle", latency_ms=(idle.mono - t0) * 1000 if idle else None, target_ms=500)
    rec.check("Android's own call state is idle again", "CALL-03 postcondition", adb.call_state().get("mCallState") == 0)
    _log_new(ctx, s, call_id, "incoming", mark)


def _log_new(ctx, s, call_id: str, kind: str, mark: int) -> None:
    got = s.wait(lambda m: m.type == "call_event" and m.op == "log_new" and m.data["call_id"] == call_id, 15,
                 after=mark)
    entry = got.data["entry"] if got else {}
    ctx.rec.check(f"call log entry arrives as log_new, type {kind}, matched to the call", "CALL-04 steps 7–8, API 2",
                  got is not None and entry.get("type") == kind,
                  json.dumps({k: entry.get(k) for k in ("type", "duration_s")}) if got else "no log_new in 15 s")


def _rejected_call(ctx, s) -> None:
    rec, adb = ctx.rec, ctx.adb
    state, ms, _ = _ring(ctx, s, FAKE["contact"], named=True)
    rec.check("second call rings on the Mac", "CALL-01", state is not None, latency_ms=ms, target_ms=200)
    if state is None:
        return
    call_id = state["call_id"]
    ctx.pause()
    mark = s.mark()
    ack, t0 = _action(ctx, s, call_id, "reject")
    rec.check("decline from the Mac: ack {}", "CALL-02 steps 4–6", ack is not None and ack.ok, _err(ack),
              latency_ms=ack.latency_ms if ack else None)
    idle = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "idle", 10, mark)
    rec.check("state idle, end_reason rejected", "CALL-02 step 7, CALL-01 API 1 logic 5",
              idle is not None and idle.data["end_reason"] == "rejected" and idle.data["answered_at"] is None,
              f"end_reason={idle.data['end_reason']}" if idle else "no idle",
              latency_ms=(idle.mono - t0) * 1000 if idle else None, target_ms=500)
    rec.check("Android's own call state is idle again", "CALL-02 postcondition", adb.call_state().get("mCallState") == 0)
    _log_new(ctx, s, call_id, "rejected", mark)
    ack, _ = _action(ctx, s, call_id, "answer", audio="phone")
    rec.check("answer after the call ended → CALL_NOT_FOUND (recently ended ids are not accepted)",
              "CALL-02 E1, API 1 logic 1", ack is not None and ack.code == "CALL_NOT_FOUND", _err(ack))


def _missed_call(ctx, s) -> None:
    rec, adb = ctx.rec, ctx.adb
    number = FAKE["unknown"]
    state, ms, _ = _ring(ctx, s, number, named=False)
    rec.check("a caller who is not a contact: number, display_name null", "CALL-01 API 1, E2",
              state is not None and state["number"] == number and state["display_name"] is None,
              "" if state else "no ringing state", latency_ms=ms, target_ms=200)
    if state is None:
        return
    call_id = state["call_id"]
    time.sleep(2)
    mark = s.mark()
    adb.gsm_cancel(number.lstrip("+"))
    idle = _wait_state(s, lambda d: d["call_id"] == call_id and d["state"] == "idle", 10, mark)
    rec.check("the caller hangs up before an answer → idle, end_reason missed", "CALL-01 API 1 logic 5",
              idle is not None and idle.data["end_reason"] == "missed", f"{idle.data['end_reason']}" if idle else "")
    _log_new(ctx, s, call_id, "missed", mark)


def _not_found(ctx, s) -> None:
    ack, _ = _action(ctx, s, str(C.uuid7()), "end")
    ctx.rec.check("end with an unknown call_id while idle → CALL_NOT_FOUND", "CALL-02 API 1, CALL-03 E1",
                  ack is not None and ack.code == "CALL_NOT_FOUND", _err(ack))
    bad = s.request("call_event", "action", {"call_id": str(uuid.uuid4()), "action": "transfer"}, validate=False)
    ctx.rec.check("an action outside the list → BAD_REQUEST", "CALL-02 API 1",
                  bad is not None and bad.code == "BAD_REQUEST", _err(bad))


def _log_sync(ctx, s) -> None:
    """CALL-04 API 1: first sync in pages of 2, ascending _ID, then an empty incremental sync, then E5."""
    rec = ctx.rec
    pages, cursor, entries, problems = 0, None, [], []
    t0 = time.monotonic()
    while pages < 100:
        data = {"limit": 2} if cursor is None else {"cursor": cursor, "limit": 2}
        ack = s.request("call_event", "log_sync", data)
        if ack is None or not ack.ok:
            problems.append(_err(ack))
            break
        pages += 1
        entries += ack.data["entries"]
        cursor = ack.data["cursor"]
        if pages == 1 and ack.data["reset"]:
            problems.append("reset on a first sync")
        if not ack.data["has_more"]:
            break
    ids = [e["entry_id"] for e in entries]
    rec.check("log_sync pages of 2 until has_more = false, entries in ascending entry_id", "CALL-04 steps 3–6, API 1",
              not problems and pages >= 2 and ids == sorted(ids) and len(ids) == len(set(ids)),
              f"{pages} pages, {len(ids)} entries {problems}", latency_ms=(time.monotonic() - t0) * 1000,
              target_ms=2000)
    kinds = {e["type"] for e in entries}
    rec.check("the log holds the answered, declined and missed calls of this run", "CALL-04 API 1 (entry)",
              {"incoming", "rejected", "missed"} <= kinds or {"incoming", "missed"} <= kinds, f"types {sorted(kinds)}")
    ack = s.request("call_event", "log_sync", {"cursor": cursor, "limit": 200})
    rec.check("incremental sync from the last cursor: nothing new", "CALL-04 API 1 logic 2, 4",
              ack is not None and ack.ok and ack.data["entries"] == [] and ack.data["has_more"] is False
              and ack.data["reset"] is False, _err(ack) if not (ack and ack.ok) else "")
    ack = s.request("call_event", "log_sync", {"cursor": "bm90IGEgY3Vyc29y", "limit": 200})
    rec.check("malformed cursor → a first sync with reset = true", "CALL-04 E5, API 1 logic 5",
              ack is not None and ack.ok and ack.data["reset"] is True,
              f"reset={ack.data['reset']} entries={len(ack.data['entries'])}" if ack and ack.ok else _err(ack))
    ack = s.request("call_event", "log_sync", {"limit": 501}, validate=False)
    rec.check("limit outside 1–500 → BAD_REQUEST", "CALL-04 API 1", ack is not None and ack.code == "BAD_REQUEST",
              _err(ack))


def _bench_report(ctx) -> None:
    """tools/bench/call_latency.py over the phone's HLBENCH lines and the fake Mac's (clock offset from the acks)."""
    bench = Path(__file__).resolve().parents[1] / "bench" / "call_latency.py"
    logs = [ctx.state_dir / "logcat-hlbench.log", ctx.state_dir / "hlbench-mac.log"]
    out = subprocess.run([sys.executable, str(bench), *map(str, logs)], capture_output=True, text=True, timeout=120)
    summary = [ln for ln in out.stdout.splitlines() if "target" in ln]
    (ctx.state_dir / "call_latency.txt").write_text(out.stdout + out.stderr, encoding="utf-8")
    ctx.rec.info("tools/bench/call_latency.py on this run", "tools/bench",
                 " | ".join(" ".join(ln.split()) for ln in summary[:8]) or out.stderr.strip()[:300])
