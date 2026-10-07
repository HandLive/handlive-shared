"""Scenario `app_calls`: CALL-05, a call of another app on the Mac, with android/tools/fake-call-app as the caller.

The fake app rings with a `CallStyle` notification of its phoneCall foreground service, goes in call with an ordinary
ongoing notification (one Hang Up action, `MODE_IN_COMMUNICATION`) the way Telegram does, and posts an unrelated
upload with a single Cancel action; it logs every intent it receives (`HLFAKECALL`). The fake Mac checks what the
phone sends: the app's label, not its package name (API 1 `app.label`; on API 35 the notification listener already
sees a package once it posts, besides the manifest's launcher query); decline and end
from the Mac; and from API 34, where an ongoing notification that is not `CallStyle` can be swiped away, a swiped
in-call notification that keeps the call on without End until the audio mode leaves communication (E11).
"""
from __future__ import annotations

import time

FAKE_APP = "app.handlive.e2e.fakecall"
FAKE_LABEL = "E2E Caller"
FAKE_CALLER = "E2E Test Caller"
IN_CALL_TITLE = "E2E in call"
LISTENER = "com.handlive.android/app.handlive.android.feature.call.appcall.AppCallListenerService"
SWIPE_API = 34                      # Android 14: an ongoing notification without CallStyle can be dismissed


def run(ctx) -> None:
    rec, adb = ctx.rec, ctx.adb
    if not _fake_app(ctx):
        return
    adb.shell(f"cmd notification allow_listener {LISTENER}", check=False)
    s = _session(ctx)
    if s is None:
        return
    _hang_up(ctx)                                   # a call left over from an earlier run
    _declined_call(ctx, s)
    _ended_from_the_mac(ctx, s)
    if ctx.sdk >= SWIPE_API:
        _swiped_in_call_notification(ctx, s)
    else:
        rec.skip("a swiped in-call notification keeps the call on", "CALL-05 E11",
                 f"API {ctx.sdk}: an ongoing notification cannot be swiped away before API {SWIPE_API}")
    rec.check("no schema violation in the app-call messages", "shared/schemas (call_event-app_call)",
              not s.violations, "; ".join(s.violations[:3]))


def _fake_app(ctx) -> bool:
    rec, adb = ctx.rec, ctx.adb
    apk = ctx.args.fake_call_apk
    if apk is not None:
        # A fresh install, so nothing of an earlier run (its notifications, the intents HandLive sent it) is left.
        adb.uninstall(FAKE_APP)
        adb.install(apk)
    if not adb.installed(FAKE_APP):
        rec.skip("calls from other apps", "CALL-05", "the fake calling app is not installed (--fake-call-apk)")
        return False
    if ctx.sdk >= 33:
        adb.grant("POST_NOTIFICATIONS", FAKE_APP)
    return True


def _session(ctx):
    """A session with app calls in effect on both sides: the Mac reports call.app_calls, the phone does once its
    notification listener is connected (a capability/update when that comes after the hello)."""
    rec = ctx.rec
    s = ctx.connect(app_calls=True)
    if s is None:
        return None
    call = ((s.peer_capability or {}).get("features") or {}).get("call") or {}
    if not call.get("app_calls"):
        upd = s.wait(lambda m: m.type == "capability" and m.op == "update"
                     and (((m.data or {}).get("features") or {}).get("call") or {}).get("app_calls"), 20)
        if upd is not None:
            s.peer_capability = upd.data
            call = upd.data["features"]["call"]
    ok = rec.check("app calls in effect: the phone reports features.call.app_calls",
                   "0.7.2, CALL-05 API 3 logic 3", call.get("app_calls") is True,
                   f"call = {call}; permissions_missing = {(s.peer_capability or {}).get('permissions_missing')}")
    return s if ok else None


def _command(ctx, cmd: str) -> None:
    ctx.pause()
    ctx.adb.shell(f"am start -n {FAKE_APP}/.CommandActivity --es cmd {cmd}", check=False)


def _hang_up(ctx) -> None:
    _command(ctx, "hangup")
    _command(ctx, "clear")
    time.sleep(1)


def _fake_events(ctx, since: float) -> list[str]:
    """What the fake app logged at `since` (device seconds) or later: a line of an earlier step or run never counts."""
    lines = ctx.adb.logcat_since(since, "-s", "HLFAKECALL:I")
    return [line.split("event=", 1)[1].split()[0] for line in lines if "event=" in line]


def _fake_event(ctx, name: str, since: float, timeout: float = 5) -> bool:
    """The fake app logged [name] since `since`: logcat may hand the line over a little after the change reached
    the Mac."""
    deadline = time.monotonic() + timeout
    while name not in _fake_events(ctx, since):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)
    return True


def _app_calls(s, call_id: str | None = None, after: int = 0) -> list:
    return s.collect(lambda m: m.type == "call_event" and m.op == "app_call"
                     and (call_id is None or m.data["call_id"] == call_id), after)


def _wait_app_call(s, pred, timeout: float, after: int):
    return s.wait(lambda m: m.type == "call_event" and m.op == "app_call" and pred(m.data), timeout, after=after)


def _action(s, call_id: str, action: str):
    t0 = time.monotonic()
    env_id, ts = s.send("call_event", "action", {"call_id": call_id, "action": action})
    return s.wait_ack(env_id, ts, t0)


def _err(ack) -> str:
    if ack is None:
        return "no ack within 10 s"
    return f"ok {ack.data}" if ack.ok else f"{ack.code} {ack.error.get('details')}"


def _ring(ctx, s, check_app: bool = False) -> dict | None:
    rec = ctx.rec
    mark = s.mark()
    t0 = time.monotonic()
    _command(ctx, "ring")
    got = _wait_app_call(s, lambda d: d["state"] == "ringing", 20, mark)
    rec.check("the fake app's ringing call reaches the Mac as call_event/app_call", "CALL-05 steps 1–5, API 1",
              got is not None, "" if got else "no ringing app_call in 20 s",
              latency_ms=(got.mono - t0) * 1000 if got else None)
    if got is None:
        return None
    data = got.data
    if check_app:
        app = data["app"]
        rec.check("app.label is the app's label, not the package name", "CALL-05 API 1 (app.label)",
                  app == {"package": FAKE_APP, "label": FAKE_LABEL}, f"app = {app}")
        rec.check("ringing: the caller from callPerson, Decline offered", "CALL-05 API 1 logic 2, 5",
                  data["caller"] == FAKE_CALLER and data["controls"]["decline"] is True
                  and data["controls"]["end"] is False, f"caller = {data['caller']!r}, controls = {data['controls']}")
    return data


def _in_call(ctx, s) -> dict | None:
    """Rings, then answers on the phone: the in-call notification must become the call's, with End."""
    rec = ctx.rec
    ringing = _ring(ctx, s)
    if ringing is None:
        return None
    mark = s.mark()
    _command(ctx, "answer")
    got = _wait_app_call(s, lambda d: d["call_id"] == ringing["call_id"] and d["state"] == "ongoing", 15, mark)
    rec.check("answered on the phone: ongoing, End from the in-call notification", "CALL-05 step 6, API 1 logic 3, 5",
              got is not None and got.data["controls"]["end"] is True,
              f"controls = {got.data['controls']}" if got else "no ongoing app_call in 15 s")
    return got.data if got else None


def _declined_call(ctx, s) -> None:
    rec = ctx.rec
    ringing = _ring(ctx, s, check_app=True)
    if ringing is None:
        return
    call_id = ringing["call_id"]
    since = ctx.adb.device_epoch()
    mark = s.mark()
    ack = _action(s, call_id, "reject")
    rec.check("decline from the Mac: ack {}", "CALL-05 step 13, API 2", ack is not None and ack.ok, _err(ack),
              latency_ms=ack.latency_ms if ack else None)
    ended = _wait_app_call(s, lambda d: d["call_id"] == call_id and d["state"] == "ended", 10, mark)
    rec.check("the app got its decline intent and the call ended as declined", "CALL-05 API 1 logic 4, API 4",
              ended is not None and ended.data["end_reason"] == "declined" and _fake_event(ctx, "decline_received", since),
              f"end_reason = {ended.data['end_reason'] if ended else None}, app events = {_fake_events(ctx, since)}")


def _ended_from_the_mac(ctx, s) -> None:
    rec = ctx.rec
    ongoing = _in_call(ctx, s)
    if ongoing is None:
        _hang_up(ctx)
        return
    call_id = ongoing["call_id"]
    since = ctx.adb.device_epoch()
    mark = s.mark()
    ack = _action(s, call_id, "end")
    rec.check("end from the Mac: ack {}", "CALL-05 step 13, API 2", ack is not None and ack.ok, _err(ack))
    ended = _wait_app_call(s, lambda d: d["call_id"] == call_id and d["state"] == "ended", 10, mark)
    rec.check("the app got its Hang Up intent, removed its notification, and the call ended as ended",
              "CALL-05 step 7, API 1 logic 4",
              ended is not None and ended.data["end_reason"] == "ended" and _fake_event(ctx, "hang_up_received", since),
              f"end_reason = {ended.data['end_reason'] if ended else None}, app events = {_fake_events(ctx, since)}")


def _swipe_in_call(ctx, attempts: int = 3) -> bool:
    """Swipes the in-call notification off the shade; a swipe started while the shade still animates may not take,
    so it is tried again until the notification is gone."""
    ui = ctx.ui
    ui.open_notifications()
    gone = False
    for _ in range(attempts):
        node = ui.wait(10, text=IN_CALL_TITLE)
        if node is None:
            break
        time.sleep(1)                               # the shade has settled
        x, y = node.center
        ctx.adb.shell(f"input swipe {x} {y} {x + 900} {y} 300", check=False)
        time.sleep(1)
        if not ui.find(ui.dump(), text=IN_CALL_TITLE):
            gone = True
            break
    ui.close_notifications()
    return gone


def _swiped_in_call_notification(ctx, s) -> None:
    rec = ctx.rec
    ongoing = _in_call(ctx, s)
    if ongoing is None:
        _hang_up(ctx)
        return
    call_id = ongoing["call_id"]
    mark = s.mark()
    swiped = _swipe_in_call(ctx)
    rec.check("swipe the fake app's in-call notification away on the shade", "Android 14 non-dismissible change",
              swiped, "" if swiped else f"no {IN_CALL_TITLE!r} on the notification shade")
    detached = _wait_app_call(s, lambda d: d["call_id"] == call_id, 10, mark)
    rec.check("the call stays ongoing on the Mac, End hidden", "CALL-05 E11",
              detached is not None and detached.data["state"] == "ongoing" and detached.data["controls"]["end"] is False,
              f"{detached.data['state']} {detached.data['controls']}" if detached else "no new app_call in 10 s")
    since = ctx.adb.device_epoch()
    mark = s.mark()
    _command(ctx, "upload")
    time.sleep(3)
    changed = _app_calls(s, call_id, mark)
    rec.check("an upload of the app never holds the detached call: nothing new for the Mac", "CALL-05 E11",
              not changed, f"{len(changed)} app_call version(s): {[m.data['controls'] for m in changed]}")
    ack = _action(s, call_id, "end")
    events = _fake_events(ctx, since)
    rec.check("End from the Mac while detached → CALL_APP_ACTION_UNAVAILABLE, the upload's Cancel never sent",
              "CALL-05 E8, E11", ack is not None and ack.code == "CALL_APP_ACTION_UNAVAILABLE"
              and "upload_cancel_received" not in events, f"{_err(ack)}; app events = {events}")
    mark = s.mark()
    _command(ctx, "hangup")
    ended = _wait_app_call(s, lambda d: d["call_id"] == call_id and d["state"] == "ended", 15, mark)
    rec.check("the app hangs up and leaves MODE_IN_COMMUNICATION: the call ends as unknown", "CALL-05 E11",
              ended is not None and ended.data["end_reason"] == "unknown" and ended.data["answered_at"] is None,
              f"end_reason = {ended.data['end_reason'] if ended else None}")
    _command(ctx, "clear")
