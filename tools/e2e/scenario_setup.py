"""Scenario `setup`: install, SET-01 part A through the UI, PAIR-01 with a PIN, then the first session (CONN-01).

Checks each spec step on the screen and on the wire; ends connected with a stored pair for the next scenarios.
"""
from __future__ import annotations

import json
import threading
import time
import uuid

import mac_crypto as C
from mac_session import SessionRefused
from transport import TransportClosed
from ui_automator import en

PERMISSION_ALLOW = "com.android.permissioncontroller:id/permission_allow_button"


def run(ctx) -> None:
    if ensure_paired(ctx, ctx.client, thorough=True):
        check_session(ctx)


def ensure_paired(ctx, client, thorough: bool = False) -> bool:
    """Installs when asked (once), taps through the first run when it shows, and pairs `client` unless the phone
    already knows its pair. `thorough` adds the wrong-PIN and early-connect checks of a first pairing."""
    adb, ui, rec = ctx.adb, ctx.ui, ctx.rec
    if ctx.args.apk and client is ctx.client and not getattr(ctx, "installed", False):
        t0 = time.monotonic()
        adb.uninstall()
        adb.install(ctx.args.apk)
        rec.check("install the debug APK", "SET-01", adb.installed(), f"{ctx.args.apk.name}",
                  latency_ms=(time.monotonic() - t0) * 1000)
        client.forget_pair()          # a new install has a new device_id and no pair
        adb.logcat_clear()
        ctx.installed = True
    adb.forward(client.port)
    adb.start_app()
    ui.pause()
    screens = dict(welcome=dict(text=en("setup.welcome_title")), pair=dict(text=en("pairing.pair_a_device")),
                   devices=dict(text=en("pairing.add_device")))
    screen = ui.wait_any(40, **screens)
    if screen is None:                    # a subscreen or another tab is open: back to the Devices tab once
        adb.shell("input keyevent KEYCODE_BACK")
        adb.start_app()
        ui.tap_text(en("pairing.devices"), timeout=10)
        screen = ui.wait_any(30, **screens)
    if screen is None:
        rec.check("the app shows its first screen", "SET-01 step 1", False, "no known screen")
        return False
    if screen[0] == "welcome":
        first_run(ctx)
    elif client.record.paired and _pair_known(client):
        rec.info(f"{client.record.name} is already paired with this phone", "PAIR-01")
        return True
    elif screen[0] == "devices":
        if client.record.paired:
            client.forget_pair()
        ui.tap_text(en("pairing.add_device"))
    return pair(ctx, client, thorough, first=screen[0] == "welcome")


def _pair_known(client) -> bool:
    try:
        s = client.session()
        s.open()
        s.close()
        return True
    except SessionRefused as exc:
        return exc.code not in ("PAIR_UNKNOWN", "PAIR_REVOKED")
    except (TransportClosed, OSError):
        return True


def first_run(ctx) -> None:
    """SET-01 part A, steps 1–7, as a user would tap through it."""
    adb, ui, rec = ctx.adb, ctx.ui, ctx.rec
    rec.check("welcome screen with the privacy explanation", "SET-01 field 1",
              ui.wait(5, text=en("setup.welcome_body_android")) is not None)
    ui.tap_text(en("common.get_started"))
    if ctx.sdk >= 33:
        primer = ui.wait(30, text=en("permission.notifications_primer_title_android"))
        rec.check("notification primer before the system dialog, one Continue", "SET-01 step 3", primer is not None)
        ui.tap_text(en("common.continue"))
        allow = ui.wait(20, rid=PERMISSION_ALLOW)
        if allow:
            ui.tap(allow)
        rec.check("POST_NOTIFICATIONS granted", "SET-01 step 4", adb.granted("POST_NOTIFICATIONS"))
    screen = ui.wait_any(45, bg=dict(text=en("permission.background_primer_title")),
                         auto=dict(text=en("setup.autostart_title")), pair=dict(text=en("pairing.pair_a_device")))
    fg = adb.foreground_service()
    rec.check("HandLiveService runs in the foreground as connectedDevice", "SET-01 step 5a",
              fg in ("connectedDevice", "foreground"), f"type {fg or 'none'}")
    rec.check("WSS server listens on 47800", "0.4.1, SET-01 step 5a", adb.listening(47800))
    texts = adb.notification_texts()
    rec.check("service notification reads “Waiting for a connection”", "CONN-01 field 6",
              en("notification.service_waiting") in texts, f"{texts}")
    if screen and screen[0] == "bg":
        ui.tap_text(en("common.continue"))
        allow = ui.wait(20, rid="android:id/button1")
        if allow:
            ui.tap(allow)
        screen = ui.wait_any(30, auto=dict(text=en("setup.autostart_title")),
                             pair=dict(text=en("pairing.pair_a_device")))
    rec.check("battery optimization exemption granted", "SET-01 step 5b", adb.battery_exempt())
    if screen and screen[0] == "auto":
        ui.tap_text(en("setup.autostart_done"))
        screen = ui.wait_any(30, pair=dict(text=en("pairing.pair_a_device")))
    rec.check("setup ends on “Pair a Device” with Scan QR Code and Enter PIN", "SET-01 step 7",
              screen is not None and screen[0] == "pair" and ui.wait(5, text=en("pairing.enter_pin")) is not None)


def _type_pin(ui, digits: str) -> bool:
    """Taps the PIN field (focus, keyboard) and types the digits one by one."""
    field = [n for n in ui.dump() if n.cls == "android.widget.EditText"]
    if not field:
        return False
    ui.tap(field[0])
    ui.type_digits(digits)
    return True


def _attempt_async(pairing, pin: str, left: int, timeout: float):
    box: dict = {}
    th = threading.Thread(target=lambda: box.setdefault("r", pairing.attempt(pin, left, offer_timeout=timeout)))
    th.start()
    return th, box


def pair(ctx, client, thorough: bool = True, first: bool = False) -> bool:
    """PAIR-01 A1–A5 with the client's PIN; `thorough` adds the wrong-PIN path (E7) and the client connecting early."""
    ui, rec = ctx.ui, ctx.rec
    pairing = client.pin_pairing()
    pin = C.new_pin()
    wrong = f"{(int(pin) + 1) % 1_000_000:06d}"
    rec.info(f"{client.record.name} shows a 6-digit PIN (CSPRNG)", "PAIR-01 A2")
    ui.tap_text(en("pairing.enter_pin"))
    rec.check("“Enter PIN” opens the PIN entry with its hint", "PAIR-01 A3, field 6",
              ui.wait(20, text=en("pairing.pin_entry_hint")) is not None)
    if not thorough:
        _type_pin(ui, pin)
        res = pairing.attempt(pin, attempts_left_if_wrong=2, offer_timeout=40)
        return _paired(ctx, client, res, first)
    # E7: a wrong PIN typed on the phone, then the Mac connects and sees the offer's mac fail.
    _type_pin(ui, wrong)
    res = pairing.attempt(pin, attempts_left_if_wrong=2, offer_timeout=40)
    rec.check("wrong PIN: the Mac answers pair/error PIN_INVALID", "PAIR-01 A5, E7",
              res.outcome == "pin_mismatch", f"{res.outcome} {res.code or ''}", latency_ms=res.timings.get("offer_ms"))
    left = ui.wait(20, text=en("pairing.pin_attempts_left", count=2))
    rec.check("the phone shows the error and “2 attempts left”", "PAIR-01 field 7",
              left is not None and ui.wait(3, text=en("error.pin_invalid")) is not None)
    # A4: a real Mac connects as soon as it sees TXT pm=1, i.e. while the user is still typing.
    th, box = _attempt_async(pairing, pin, 1, 25)
    time.sleep(4)
    field_left = any(n.cls == "android.widget.EditText" for n in ui.dump())
    rec.check("the PIN field stays usable while the Mac is already connected", "PAIR-01 A3–A4",
              field_left, "" if field_left else "the phone replaced the PIN entry with “Pairing…” as soon as the "
                                                 "Mac connected; the PIN can no longer be typed")
    if field_left:
        _type_pin(ui, pin)
    th.join()
    res = box["r"]
    if res.outcome != "paired":
        rec.info("retry with the PIN typed before the Mac connects", "PAIR-01", f"early attempt: {res.outcome} "
                                                                                f"{res.code or ''}")
        ui.tap_text(en("common.cancel"))
        ui.tap_text(en("pairing.add_device"), timeout=20)
        ui.tap_text(en("pairing.enter_pin"))
        _type_pin(ui, pin)
        res = pairing.attempt(pin, attempts_left_if_wrong=2, offer_timeout=40)
    return _paired(ctx, client, res, first)


def _paired(ctx, client, res, first: bool) -> bool:
    ui, rec = ctx.ui, ctx.rec
    rec.check("pairing completes: offer, confirm, done verified", "PAIR-01 steps 9–11, API 3–5",
              res.outcome == "paired", f"{res.outcome} {res.code or ''}", latency_ms=res.timings.get("total_ms"),
              target_ms=5000)
    rec.check("pair messages match the schemas", "0.5.1, shared/schemas", not res.violations,
              "; ".join(res.violations[:2]))
    if res.outcome != "paired":
        return False
    client.save()
    title = ui.wait(20, text=en("pairing.paired_with", device_name=client.record.name))
    grouped = f"{res.security_code[:4]} {res.security_code[4:]}"
    rec.check(f"“Paired with {client.record.name}” on the phone", "PAIR-01 step 12", title is not None)
    rec.check("same Security Code on the phone and the client", "PAIR-02 field 10",
              ui.wait(5, text=grouped) is not None, f"Mac {res.security_code}")
    ui.tap_text(en("common.done"))
    if first:
        feature_list = ui.wait_any(8, perms=dict(text=en("permission.grant")),
                                   sms=dict(text=en("settings.sms_messages")))
        rec.check("after the first pairing the app opens the feature list", "SET-01 step 8", feature_list is not None,
                  "" if feature_list else f"screen: {ui.screen_texts()[:6]}")
    return True


def check_session(ctx) -> None:
    """CONN-01 steps 4–10 and API 4–7, one connection per pair (4409), the handshake errors, idle close."""
    adb, rec, client = ctx.adb, ctx.rec, ctx.client
    s = ctx.connect()
    if s is None:
        return
    rec.check("session handshake on the LAN", "CONN-01 API 4–5", True, "", latency_ms=s.timings["handshake_ms"],
              target_ms=300)
    cap = s.peer_capability or {}
    rec.check("phone capability/hello is the first encrypted envelope and matches the schema", "0.6.3 step 4, 0.7.2",
              cap.get("platform") == "android" and not s.violations, json.dumps(cap.get("permissions_missing")))
    time.sleep(1.5)
    texts = adb.notification_texts()
    rec.check("service notification reads “Connected to <Mac>”", "CONN-01 field 6, step 10",
              en("notification.service_connected_to", device_name=client.record.name) in texts, f"{texts}")
    rec.check("the Mac is listed on the Devices tab", "PAIR-02 field 1",
              ctx.ui.wait(10, text=client.record.name) is not None)
    # One /v1/ctl per pair: a new session replaces the old one with session/bye {replaced}, then 4409.
    old = s
    new = client.session()
    new.open()
    bye = old.wait(lambda m: m.type == "session" and m.op == "bye", 5)
    deadline = time.monotonic() + 5
    while old.closed is None and time.monotonic() < deadline:
        time.sleep(0.2)
    rec.check("a new session replaces the old: session/bye replaced, close 4409", "CONN-01 step 7, 0.8.3",
              bye is not None and (bye.data or {}).get("reason") == "replaced" and old.closed is not None
              and old.closed[0] == 4409, f"bye={bye.data if bye else None} close={old.closed}")
    ctx.session = new
    old.abort()
    _handshake_errors(ctx)


def _handshake_errors(ctx) -> None:
    rec, client = ctx.rec, ctx.client
    real = client.record.pair_id
    client.record.pair_id = str(uuid.uuid4())        # a pair the phone does not know
    try:
        client.session().open()
        ok, detail = False, "session opened"
    except SessionRefused as exc:
        ok, detail = exc.code == "PAIR_UNKNOWN" and exc.close_code == 4401, f"{exc.code} close {exc.close_code}"
    finally:
        client.record.pair_id = real
    rec.check("unknown pair: session/error PAIR_UNKNOWN, close 4401", "CONN-01 API 4 logic 1, API 6", ok, detail)
    code, waited = _wait_close(client.lan("/v1/ctl"), 30)
    rec.check("a connection that never sends session/hello is closed with 4408", "CONN-01 API 3 logic 2, 0.8.3",
              code == 4408, f"close {code}", latency_ms=waited, target_ms=5000)
    s = client.session(open_transport=lambda: client.lan("/v1/ctl", keepalive=False))
    s.open()
    t0 = time.monotonic()
    while s.closed is None and time.monotonic() - t0 < 75:
        time.sleep(0.5)
    rec.check("a session silent for more than 45 s is closed with 4411", "CONN-02 step 3, 0.8.3",
              s.closed is not None and s.closed[0] == 4411, f"close {s.closed}",
              latency_ms=(time.monotonic() - t0) * 1000, target_ms=45000)
    s.abort()


def _wait_close(transport, limit: float) -> tuple[int | None, float]:
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < limit:
            transport.recv(1.0)
    except TransportClosed as exc:
        return exc.code, (time.monotonic() - t0) * 1000
    transport.abort()
    return None, (time.monotonic() - t0) * 1000
