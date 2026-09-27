"""Scenario `sms`: SMS-01…05 against the real SMS provider of the emulator.

Incoming messages come from the emulator's modem (`adb emu sms send`); history for paging is seeded straight into the
provider by the shell (fake numbers only); replies go out through the phone's SmsManager to the emulator's own number,
which the emulator loops back as an incoming message.
"""
from __future__ import annotations

import base64
import json
import re
import time

import mac_crypto as C
from bench_lines import peer8
from scenario_common import FAKE, features, grant_and_refresh
from ui_automator import en

SMS_PERMISSIONS = ["READ_SMS", "SEND_SMS", "READ_CONTACTS", "READ_PHONE_STATE"]
FAKE_IN = FAKE["sms_in"]                      # fictional numbers (555-01xx), see scenario_common
SEED = FAKE["seed"]
SEED_PER_THREAD = 16                          # 3 × 16 × 4000 characters > 180 KiB: a first sync of 2 pages
SEED_BODY = 4000                              # a long concatenated SMS; fewer rows keep a busy emulator responsive
PAGE_MAX_BYTES = 180 * 1024


def run(ctx) -> None:
    rec = ctx.rec
    cap = grant_and_refresh(ctx, SMS_PERMISSIONS, "SMS")
    sms = features(cap, "sms")
    rec.check("SMS in effect: enabled, can_send, SIM list", "0.7.2, CONN-01 API 7",
              sms.get("enabled") is True and sms.get("can_send") is True and len(sms.get("sims") or []) >= 1,
              json.dumps(sms))
    if ctx.session is None:
        return
    ctx.adb.allow_sms_writes()
    ctx.disconnect()
    seeded = _seed(ctx)
    s = ctx.connect()
    if s is None:
        return
    body, incoming = _incoming(ctx, s)
    cursor, threads = _first_sync(ctx, s, body, seeded)
    _catch_up(ctx, s, cursor)
    _history(ctx, s, threads, seeded)
    _send(ctx, s)
    _send_errors(ctx, s)
    _read_changed(ctx, s, incoming)
    rec.check("no schema violation in the SMS messages", "shared/schemas", not s.violations,
              "; ".join(s.violations[:3]))
    if ctx.args.shared_device:
        rec.skip("READ_SMS revoked: PERMISSION_MISSING and the suggestion notification", "SMS-01 E2, SET-01 field 17",
                 "revoking a permission restarts the app, which would cut the other clients of a shared emulator")
    else:
        _permission_lost(ctx)


def _seed(ctx) -> bool:
    """History for paging: 3 conversations × 16 messages of 4000 characters (> 180 KiB in all), inserted in small
    batches with a pause, with no session open (the observer broadcasts every new row)."""
    adb, rec = ctx.adb, ctx.rec
    where = " OR ".join(f"address='{a}'" for a in SEED)
    rows = adb.query("content://sms", "_id", where)
    if len(rows) == len(SEED) * SEED_PER_THREAD:
        rec.info("history already seeded", "SMS-01", f"{len(rows)} messages")
        return True
    if ctx.args.shared_device:
        rec.skip("seed 48 long messages for the 180 KiB paging checks", "SMS-01 setup",
                 "on the shared emulator each provider insert took over 30 s (the default SMS app reacts to every "
                 "row); the paging over 180 KiB was checked on a dedicated emulator")
        return False
    adb.content("delete", "content://sms", where=where)
    now = C.now_ms()
    lines = []
    for t, address in enumerate(SEED):
        for i in range(SEED_PER_THREAD):
            body = (f"E2E seed {t} {i} " + "lorem ipsum dolor sit amet " * 160)[:SEED_BODY]
            date = now - 86_400_000 - (t * SEED_PER_THREAD + i) * 60_000
            lines.append(f"content insert --uri content://sms/inbox --bind address:s:{address} "
                         f"--bind body:s:'{body}' --bind date:l:{date} --bind read:i:1")
    t0 = time.monotonic()
    out = ""
    for b in range(0, len(lines), 8):
        script = ctx.state_dir / "hl_seed.sh"
        script.write_text("\n".join(lines[b:b + 8]) + "\necho seeded\n", encoding="utf-8")
        adb.push(script, "/data/local/tmp/hl_seed.sh")
        out = adb.shell("sh /data/local/tmp/hl_seed.sh", timeout=300)
        time.sleep(1)
    count = len(adb.query("content://sms", "_id", where))
    return rec.check("history seeded into the SMS provider", "SMS-01 setup", "seeded" in out and count == len(lines),
                     f"{count} messages", latency_ms=(time.monotonic() - t0) * 1000)


def _incoming(ctx, s) -> tuple[str, dict | None]:
    """SMS-02: a message from the modem reaches the Mac as sms/new."""
    rec = ctx.rec
    body = f"E2E incoming {C.uuid7()[-8:]}"
    mark = s.mark()
    ctx.pause()
    t0 = time.monotonic()
    ctx.adb.sms_to_phone(FAKE_IN.lstrip("+"), body)
    got = s.wait(lambda m: m.type == "sms" and m.op == "new" and (m.data or {}).get("message", {}).get("body") == body,
                 30, after=mark)
    ms = (got.mono - t0) * 1000 if got else None
    msg, thread = (got.data["message"], got.data["thread"]) if got else ({}, {})
    rec.check("incoming SMS reaches the Mac as sms/new", "SMS-02 steps 1–5, API 1", got is not None,
              "" if got else "no sms/new within 30 s", latency_ms=ms, target_ms=500)
    if got:
        rec.check("sms/new: inbox, E.164 sender, unread, thread summary", "SMS-02 API 1, 5.1.5",
                  msg.get("box") == "inbox" and msg.get("address") == FAKE_IN and msg.get("read") is False
                  and re.fullmatch(r"sms:\d+", msg.get("message_key", "")) is not None
                  and thread.get("addresses") == [FAKE_IN] and thread.get("snippet") == body
                  and thread.get("unread_count", 0) >= 1 and msg.get("local_id") is None,
                  json.dumps({k: msg.get(k) for k in ("box", "read", "sub_id")}))
    return body, (got.data if got else None)


def _sync_all(s, cursor: str | None, limits=(200, 50)) -> tuple[list, str | None, list[str]]:
    pages, token, problems = [], None, []
    for _ in range(50):
        data = {"thread_limit": limits[0], "per_thread_limit": limits[1]}
        if cursor:
            data["cursor"] = cursor
        if token:
            data["page_token"] = token
        ack = s.request("sms", "sync", data)
        if ack is None or not ack.ok:
            problems.append("no ack" if ack is None else f"{ack.code}")
            break
        pages.append(ack)
        if not ack.data["has_more"]:
            break
        token = ack.data.get("page_token")
    return pages, (pages[-1].data["cursor"] if pages else None), problems


def _first_sync(ctx, s, incoming_body: str, seeded: bool) -> tuple[str | None, dict]:
    rec = ctx.rec
    t0 = time.monotonic()
    pages, cursor, problems = _sync_all(s, None)
    ms = (time.monotonic() - t0) * 1000
    msgs = [m for p in pages for m in p.data["messages"]]
    threads = {t["thread_id"]: t for p in pages for t in p.data["threads"]}
    keys = [m["message_key"] for m in msgs]
    sizes = [len(C.compact_json(p.raw).encode()) for p in pages]
    rec.check("first sync pages until has_more = false", "SMS-01 steps 3–8, API 1", pages and not problems,
              f"{len(pages)} pages, {len(msgs)} messages, {len(threads)} threads {problems}", latency_ms=ms,
              target_ms=20000)
    rec.check("paging: page_token on all but the last page, same cursor on every page" +
              (", more than one page" if seeded else ""), "SMS-01 API 1 logic 4, 7",
              (len(pages) >= 2 or not seeded) and all(p.data.get("page_token") for p in pages[:-1])
              and len({p.data["cursor"] for p in pages}) == 1, f"{len(pages)} pages")
    rec.check("each page ≤ 500 messages and ≤ 180 KiB of plaintext", "SMS-01 API 1 logic 7, SMS_PAGE_MAX_BYTES",
              all(len(p.data["messages"]) <= 500 for p in pages) and max(sizes or [0]) <= PAGE_MAX_BYTES + 512,
              f"page sizes {sizes}")
    rec.check("no message twice across pages", "SMS-01 API 1 logic 3", len(keys) == len(set(keys)))
    if seeded:
        mine = [t for t in threads.values() if t["addresses"] and t["addresses"][0] in SEED]
        per_thread = {t["addresses"][0]: sum(1 for m in msgs if m["thread_id"] == t["thread_id"]) for t in mine}
        rec.check("the seeded conversations came with their messages", "SMS-01 API 1 logic 5",
                  len(mine) == len(SEED) and all(n == min(SEED_PER_THREAD, 50) for n in per_thread.values()),
                  f"{per_thread}")
    last = pages[-1].data if pages else {}
    new = next((m for m in msgs if m["body"] == incoming_body), None)
    rec.check("the new message is in the sync and the last page lists its conversation as unread",
              "SMS-01 step 9, API 1", new is not None and new["read"] is False
              and any(u["thread_id"] == new["thread_id"] for u in last.get("unread", [])),
              f"found={new is not None} unread={last.get('unread')}")
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        ok = decoded.get("v") == 1 and "id" in decoded and "t" in decoded
    except (ValueError, TypeError, AttributeError):
        ok, decoded = False, cursor
    rec.info("cursor format {v, id, t} (opaque to the client)", "SMS-01 API 1 logic 2",
             "readable" if ok else f"unexpected {decoded}")
    return cursor, threads


def _catch_up(ctx, s, cursor: str | None) -> None:
    rec = ctx.rec
    body = f"E2E catch-up {C.uuid7()[-8:]}"
    mark = s.mark()
    ctx.adb.sms_to_phone(FAKE_IN.lstrip("+"), body)
    got = s.wait(lambda m: m.type == "sms" and m.op == "new" and m.data["message"]["body"] == body, 30, after=mark)
    pages, new_cursor, problems = _sync_all(s, cursor)
    msgs = [m for p in pages for m in p.data["messages"]]
    rec.check("the second incoming SMS also arrives as sms/new", "SMS-02", got is not None)
    rec.check("catch-up sync from the cursor returns only the newer messages", "SMS-01 API 1 logic 6",
              not problems and any(m["body"] == body for m in msgs) and len(msgs) <= 5 and new_cursor != cursor
              and pages[-1].data.get("unread") is not None, f"{len(msgs)} messages {problems}")
    bad = s.request("sms", "sync", {"cursor": "not-a-cursor", "thread_limit": 200, "per_thread_limit": 50})
    rec.check("malformed cursor → SMS_CURSOR_INVALID (reason cursor)", "SMS-01 E5, 0.8.1",
              bad is not None and not bad.ok and bad.code == "SMS_CURSOR_INVALID"
              and (bad.error.get("details") or {}).get("reason") == "cursor", _err(bad))
    bad = s.request("sms", "sync", {"page_token": "not-a-token", "thread_limit": 200, "per_thread_limit": 50})
    rec.check("malformed page_token → SMS_CURSOR_INVALID (reason page_token)", "SMS-01 E5, API 1 logic 4",
              bad is not None and not bad.ok and bad.code == "SMS_CURSOR_INVALID"
              and (bad.error.get("details") or {}).get("reason") == "page_token", _err(bad))
    bad = s.request("sms", "sync", {"thread_limit": 0, "per_thread_limit": 50}, validate=False)
    rec.check("thread_limit out of range → BAD_REQUEST", "SMS-01 API 1", bad is not None and bad.code == "BAD_REQUEST",
              _err(bad))


def _history(ctx, s, threads: dict, seeded: bool) -> None:
    """SMS-03: load older messages of one conversation, newest first, until has_more = false — pages of 15 over a
    seeded conversation, or pages of 1 over the test sender's conversation when nothing was seeded."""
    rec = ctx.rec
    address, limit = (SEED[0], 15) if seeded else (FAKE_IN, 1)
    thread = next((t for t in threads.values() if t["addresses"] == [address]), None)
    if thread is None:
        rec.check("history: the conversation is known", "SMS-03", False)
        return
    before, seen, pages, order_ok = C.now_ms() + 60_000, [], 0, True
    t0 = time.monotonic()
    while pages < 60:
        ack = s.request("sms", "history", {"thread_id": thread["thread_id"], "before_ts": before, "limit": limit})
        if ack is None or not ack.ok:
            break
        pages += 1
        msgs = ack.data["messages"]
        ts = [m["ts"] for m in msgs]
        order_ok &= ts == sorted(ts, reverse=True) and all(t < before for t in ts)
        seen += [m["message_key"] for m in msgs]
        if not ack.data["has_more"] or not msgs:
            break
        before = min(ts)
    expected = (pages == -(-SEED_PER_THREAD // 15) and len(seen) == SEED_PER_THREAD) if seeded else pages >= 2
    rec.check(f"history pages of {limit}, newest first, until has_more = false", "SMS-03 steps 9–11, API 1",
              expected and len(set(seen)) == len(seen) and order_ok, f"{pages} pages, {len(seen)} messages",
              latency_ms=(time.monotonic() - t0) * 1000)
    bad = s.request("sms", "history", {"thread_id": 987654321, "before_ts": C.now_ms(), "limit": 50})
    rec.check("unknown conversation → SMS_THREAD_NOT_FOUND", "SMS-03 E3, API 1",
              bad is not None and not bad.ok and bad.code == "SMS_THREAD_NOT_FOUND", _err(bad))


def _statuses(s, local_id: str, after: int, until: float) -> list[str]:
    seq = []
    while time.monotonic() < until:
        got = s.collect(lambda m: m.type == "sms" and m.op == "status" and m.data["local_id"] == local_id, after)
        seq = [m.data["status"] for m in got]
        if seq and seq[-1] in ("delivered", "failed"):
            break
        time.sleep(0.5)
    return seq


def _send(ctx, s) -> None:
    """SMS-04: a reply sent from the Mac through the phone to this very emulator, which loops it back. The
    emulator's console port as a short code (3–8 digits, API 1 logic 2) reaches it; its own number (+1 555…) is not
    a valid number for libphonenumber, so the phone refuses it with SMS_INVALID_ADDRESS as the spec says."""
    rec = ctx.rec
    sims = features(s.peer_capability, "sms").get("sims") or []
    body = f"E2E reply {C.uuid7()[-8:]}"
    local_id = C.uuid7()
    recipient = ctx.adb.console_port()
    data = {"local_id": local_id, "addresses": [recipient], "body": body}
    if sims:
        data["sub_id"] = sims[0]["sub_id"]
    mark = s.mark()
    s.bench.line("sms_send_tap", local=local_id)
    t0 = time.monotonic()
    ack = s.request("sms", "send", data)
    s.bench.line("sms_send_sent", local=local_id, peer=peer8(ctx.client.record.peer_device_id), attempt=1, via="lan")
    if ack is not None:
        s.bench.line("sms_send_ack_received", local=local_id, peer=peer8(ctx.client.record.peer_device_id),
                     ok=ack.ok, code=ack.code)
    rec.check("sms/send to a short code acked {accepted, parts}", "SMS-04 steps 5–7, API 1 logic 1–2",
              ack is not None and ack.ok and ack.data == {"accepted": True, "parts": 1}, _err(ack),
              latency_ms=ack.latency_ms if ack else None, target_ms=300)
    if ack is None or not ack.ok:
        return
    seq = _statuses(s, local_id, mark, time.monotonic() + 30)
    order = ["sending", "sent", "delivered"]
    forward = all(order.index(a) < order.index(b) for a, b in zip(seq, seq[1:]) if a in order and b in order)
    sent_at = next((m.mono for m in s.collect(lambda m: m.type == "sms" and m.op == "status"
                                              and m.data["local_id"] == local_id and m.data["status"] == "sent", mark)),
                   None)
    rec.check("sms/status moves forward only: sending → sent (→ delivered)", "SMS-04 API 2 logic 1–2",
              "sent" in seq and forward and "failed" not in seq, " → ".join(seq),
              latency_ms=(sent_at - t0) * 1000 if sent_at else None, target_ms=2000)
    sent = s.wait(lambda m: m.type == "sms" and m.op == "new" and m.data["message"]["box"] == "sent"
                  and m.data["message"]["body"] == body, 20, after=mark)
    rec.check("the Sent row comes back as sms/new with our local_id", "SMS-04 step 10, API 4",
              sent is not None and sent.data["message"].get("local_id") == local_id,
              "" if sent else "no sms/new box=sent within 20 s")
    own = ctx.adb.own_number()
    if own:
        bad = s.request("sms", "send", {"local_id": C.uuid7(), "addresses": [own], "body": body})
        rec.check("the emulator's own +1 555 number is refused (not a valid number for libphonenumber)",
                  "SMS-04 API 1 logic 2, E4", bad is not None and not bad.ok and bad.code == "SMS_INVALID_ADDRESS",
                  _err(bad))
    rec.skip("a reply looped back to this emulator as an incoming SMS", "SMS-04 → SMS-02",
             "the emulator does not deliver an SMS to itself through its console port, and its own number is "
             "refused as above; incoming SMS are covered by `adb emu sms send`")
    # Deduplication: the same local_id in a new envelope is accepted again but not sent again (API 1 logic 4).
    again = s.request("sms", "send", data)
    time.sleep(8)
    sent_rows = s.collect(lambda m: m.type == "sms" and m.op == "new" and m.data["message"]["box"] == "sent"
                          and m.data["message"]["body"] == body, mark)
    rec.check("same local_id again: {accepted, parts} and no second SMS", "SMS-04 API 1 logic 4",
              again is not None and again.ok and again.data == ack.data if ack else False,
              f"sent rows {len({m.data['message']['message_key'] for m in sent_rows})}")
    rec.check("… exactly one Sent row for that local_id", "SMS-04 special requirements (no duplicate sends)",
              len({m.data["message"]["message_key"] for m in sent_rows}) == 1)
    long_body = "E2E long reply " + "x" * 385
    ack = s.request("sms", "send", {"local_id": C.uuid7(), "addresses": [recipient], "body": long_body})
    rec.check("a 400-character reply is split into 3 parts", "SMS-04 API 3 (divideMessage)",
              ack is not None and ack.ok and ack.data.get("parts") == 3, _err(ack))


def _send_errors(ctx, s) -> None:
    rec = ctx.rec
    cases = [
        ("recipient that is not a number → SMS_INVALID_ADDRESS", {"addresses": ["not a number"], "body": "x"},
         "SMS_INVALID_ADDRESS", "SMS-04 E4"),
        ("empty body → BAD_REQUEST", {"addresses": [FAKE_IN], "body": ""}, "BAD_REQUEST", "SMS-04 E5"),
        ("1601 characters → PAYLOAD_TOO_LARGE", {"addresses": [FAKE_IN], "body": "y" * 1601}, "PAYLOAD_TOO_LARGE",
         "SMS-04 E5"),
        ("two recipients → BAD_REQUEST", {"addresses": [FAKE_IN, SEED[0]], "body": "x"}, "BAD_REQUEST",
         "SMS-04 API 1"),
        ("inactive SIM → SMS_SIM_UNAVAILABLE with the valid sims", {"addresses": [FAKE_IN], "body": "x",
                                                                   "sub_id": 99}, "SMS_SIM_UNAVAILABLE",
         "SMS-04 E6"),
    ]
    for name, data, code, spec in cases:
        ack = s.request("sms", "send", {"local_id": C.uuid7(), **data}, validate=False)
        ok = ack is not None and not ack.ok and ack.code == code
        if ok and code == "SMS_SIM_UNAVAILABLE":
            ok = isinstance((ack.error.get("details") or {}).get("sims"), list)
        rec.check(name, spec, ok, _err(ack))


def _read_changed(ctx, s, incoming) -> None:
    """SMS-05: reading on the phone (the default SMS app sets read = 1) → sms/read_changed."""
    rec = ctx.rec
    if not incoming:
        return
    thread_id = incoming["thread"]["thread_id"]
    mark = s.mark()
    t0 = time.monotonic()
    ctx.adb.content("update", "content://sms/inbox", "read:i:1", where=f"thread_id={thread_id}")
    got = s.wait(lambda m: m.type == "sms" and m.op == "read_changed" and m.data["thread_id"] == thread_id, 15,
                 after=mark)
    rec.check("messages read on the phone → sms/read_changed with unread_count 0", "SMS-05 steps 2–5, API 1",
              got is not None and got.data["unread_count"] == 0, json.dumps(got.data) if got else "none in 15 s",
              latency_ms=(got.mono - t0) * 1000 if got else None, target_ms=1000)


def _permission_lost(ctx) -> None:
    """SMS-01 E2, SET-01 field 17: READ_SMS revoked → PERMISSION_MISSING and the suggestion notification."""
    rec, adb = ctx.rec, ctx.adb
    ctx.disconnect()
    adb.revoke("READ_SMS")                     # Android kills the process; START_STICKY brings the service back
    s = None
    for _ in range(12):
        time.sleep(5)
        if adb.listening(47800):
            s = ctx.connect(attempts=2)
            if s:
                break
    if s is None:
        rec.check("service back after the permission was revoked", "SET-01 API 2 logic 4", False)
        adb.grant("READ_SMS")
        return
    missing = (s.peer_capability or {}).get("permissions_missing", [])
    rec.check("READ_SMS revoked → capability lists it missing", "SMS-02 E6, 0.7.2", "READ_SMS" in missing,
              f"{missing}")
    ack = s.request("sms", "sync", {"thread_limit": 200, "per_thread_limit": 50})
    rec.check("sms/sync → PERMISSION_MISSING android.permission.READ_SMS", "SMS-01 E2",
              ack is not None and not ack.ok and ack.code in ("PERMISSION_MISSING", "FEATURE_DISABLED")
              and (ack.code == "FEATURE_DISABLED"
                   or (ack.error.get("details") or {}).get("permission") == "android.permission.READ_SMS"), _err(ack))
    time.sleep(2)
    texts = adb.notification_texts()
    want = en("notification.permission_sms_read", device_name=ctx.client.record.name)
    rec.check("permission suggestion notification on the phone", "SET-01 field 17", want in texts, f"{texts}")
    adb.grant("READ_SMS")
    adb.start_app()
    ctx.ui.pause()


def _err(ack) -> str:
    if ack is None:
        return "no ack within 10 s"
    return f"ok {ack.data}" if ack.ok else f"{ack.code} {ack.error.get('details')}"
