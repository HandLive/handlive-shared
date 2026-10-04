"""Scenario `clipboard`: CLIP-02 (Mac → phone text), CLIP-03 (chunked text and images), and CLIP-01 from the phone
through the paths that need no Accessibility service (the Send Clipboard button, the Share target).

The phone's clipboard cannot be read from adb, so the Mac → phone write is proven by sending it back: after
CLIP_LOOP_WINDOW the Send Clipboard button reads the clipboard and the same text arrives at the Mac (CLIP-01 API 3).
"""
from __future__ import annotations

import hashlib
import math
import http.server
import os
import sys
import threading
import time
import zlib
from pathlib import Path

import mac_crypto as C
from bench_lines import peer8
from ui_automator import en

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from make_test_png import chunk as png_chunk  # noqa: E402

CHUNK = 65_536
SHARE_TARGET = "app.handlive.android/app.handlive.android.feature.clipboard.component.ClipboardShareTarget"


def test_png(target_bytes: int) -> tuple[bytes, int]:
    """A PNG of random pixels close to the target size (tools/bench/make_test_png.py); returns (bytes, side)."""
    import struct
    side = max(1, int((target_bytes / 3) ** 0.5))
    rows = b"".join(b"\x00" + os.urandom(side * 3) for _ in range(side))
    png = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
           + png_chunk(b"IDAT", zlib.compress(rows, 1)) + png_chunk(b"IEND", b""))
    return png, side


def push_text(ctx, s, text: str, clip_id: str | None = None, env_id: str | None = None, ts: int | None = None):
    clip_id = clip_id or C.uuid7()
    data = {"clip_id": clip_id, "kind": "text", "mime": "text/plain", "text": text, "sensitive": False,
            "origin_ts": C.now_ms(), "source": "mac", "origin_device_id": ctx.client.record.device_id}
    s.bench.line("clip_read", clip=clip_id, kind="text", bytes=len(text.encode()), source="mac")
    ack = s.request("clipboard", "push", data, env_id=env_id, ts=ts)
    s.bench.line("clip_sent", clip=clip_id, peer=peer8(ctx.client.record.peer_device_id))
    if ack is not None:
        s.bench.line("ack_received", clip=clip_id, peer=peer8(ctx.client.record.peer_device_id),
                     status=(ack.data or {}).get("status", "rejected") if ack.ok else "rejected")
    return clip_id, ack


def push_transfer(ctx, s, kind: str, mime: str, blob: bytes, width: int | None = None, height: int | None = None,
                  size: int | None = None, send_chunks: bool = True, corrupt: bool = False):
    """CLIP-03 API 3–4: push with `transfer`, then the chunks; the ack comes after the last chunk is checked."""
    clip_id, transfer_id = C.uuid7(), C.uuid7()
    size = len(blob) if size is None else size
    data = {"clip_id": clip_id, "kind": kind, "mime": mime,
            "transfer": {"transfer_id": transfer_id, "size": size, "sha256": C.b64u(hashlib.sha256(blob).digest()),
                         "chunk_size": CHUNK, "chunk_count": max(1, math.ceil(size / CHUNK))},
            "sensitive": False, "origin_ts": C.now_ms(), "source": "mac",
            "origin_device_id": ctx.client.record.device_id}
    if kind == "image":
        data.update(width=width, height=height)
    s.bench.line("clip_read", clip=clip_id, kind=kind, bytes=len(blob), source="mac")
    t0 = time.monotonic()
    env_id, ts = s.send("clipboard", "push", data)
    wire = bytes([blob[0] ^ 0xFF]) + blob[1:] if corrupt else blob
    if send_chunks:
        for i in range(0, len(wire), CHUNK):
            s.send_chunk(transfer_id, i // CHUNK, wire[i:i + CHUNK])
    ack = s.wait_ack(env_id, ts, time.monotonic(), 10)
    return clip_id, ack, (time.monotonic() - t0) * 1000


def run(ctx) -> None:
    rec = ctx.rec
    s = ctx.connect()
    if s is None:
        return
    cap = (s.peer_capability or {}).get("features", {}).get("clipboard", {})
    rec.check("clipboard is on at the phone (QC1)", "CLIP-02 precondition 2, 0.7.2", cap.get("enabled") is True,
              f"auto_send={cap.get('auto_send')}")
    text = f"HandLive e2e clip {C.uuid7()[-12:]}"
    clip_id, ack = push_text(ctx, s, text)
    rec.check("Mac → phone text: ack applied", "CLIP-02 step 9–10, CLIP-01 API 5",
              ack is not None and ack.ok and (ack.data or {}).get("status") == "applied",
              _ack_text(ack), latency_ms=ack.latency_ms if ack else None, target_ms=50)
    t_applied = time.monotonic()
    _, dup = push_text(ctx, s, text, clip_id=clip_id)
    rec.check("same clip_id again: ignored / duplicate", "CLIP-01 API 5 logic 6, QC6",
              dup is not None and dup.ok and dup.data == {"clip_id": clip_id, "status": "ignored",
                                                           "reason": "duplicate"}, _ack_text(dup))
    again = s.request("clipboard", "push", {"clip_id": clip_id, "kind": "text", "mime": "text/plain", "text": text,
                                            "sensitive": False, "origin_ts": C.now_ms(), "source": "mac",
                                            "origin_device_id": ctx.client.record.device_id},
                      env_id=ack.env_id if ack else None, ts=ack.ts if ack else None)
    rec.check("same envelope id again: the earlier ack is resent", "0.5.1 rule 2",
              again is not None and ack is not None and again.raw.get("data") == ack.raw.get("data"),
              _ack_text(again))
    _loop_guard_and_manual_send(ctx, s, text, t_applied)
    _share_target(ctx, s)
    _phone_to_mac_image(ctx, s)
    _chunked(ctx, s)


def _ack_text(ack) -> str:
    if ack is None:
        return "no ack within 10 s"
    return f"ok data={ack.data}" if ack.ok else f"error {ack.code} {ack.error.get('details')}"


def _tap_send_clipboard(ctx) -> bool:
    """The "Send Clipboard" action of the service notification (CLIP-01 field 4), expanded in the shade."""
    ui = ctx.ui
    ui.open_notifications()
    label = en("clipboard.send")
    for _ in range(3):
        nodes = ui.dump()
        hit = [n for n in nodes if n.text.lower() == label.lower() or n.desc.lower() == label.lower()]
        if hit:
            ui.tap(hit[0])
            return True
        row = [n for n in nodes if n.text == en("notification.service_connected_to",
                                                   device_name=ctx.client.record.name)]
        expand = [n for n in nodes if n.rid == "android:id/expand_button"]
        if row and expand:
            near = min(expand, key=lambda n: abs(n.center[1] - row[0].center[1]))
            ui.tap(near)
        elif row:
            x, y = row[0].center
            ctx.adb.shell(f"input swipe {x} {y} {x} {y + 400} 300")
            ui.pause()
    ui.close_notifications()
    return False


def _loop_guard_and_manual_send(ctx, s, text: str, t_applied: float) -> None:
    rec = ctx.rec
    wait = 5.5 - (time.monotonic() - t_applied)       # CLIP_LOOP_WINDOW = 5 s (QC4)
    if wait > 0:
        time.sleep(wait)
    mark = s.mark()
    tapped = _tap_send_clipboard(ctx)
    rec.check("the service notification offers Send Clipboard", "CLIP-01 field 4, SET-01 field 5", tapped)
    if not tapped:
        return
    got = s.wait(lambda m: m.type == "clipboard" and m.op == "push", 20, after=mark)
    d = got.data if got else {}
    rec.check("phone → Mac through the notification button (no Accessibility): the phone's clipboard holds the "
              "text the Mac sent", "CLIP-01 API 3, CLIP-02 postcondition",
              got is not None and d.get("text") == text and d.get("source") == "manual"
              and d.get("origin_device_id") == ctx.client.record.peer_device_id,
              f"source={d.get('source')} same_text={d.get('text') == text}" if got else "no clipboard/push in 20 s")
    ctx.ui.close_notifications()


def _share_target(ctx, s) -> None:
    rec = ctx.rec
    text = f"HandLive e2e share {C.uuid7()[-12:]}"
    mark = s.mark()
    t0 = time.monotonic()
    out = ctx.adb.shell(f"am start -a android.intent.action.SEND -t text/plain "
                        f"--es android.intent.extra.TEXT '{text}' -n {SHARE_TARGET}", check=False)
    got = s.wait(lambda m: m.type == "clipboard" and m.op == "push", 20, after=mark)
    d = got.data if got else {}
    rec.check("phone → Mac through the Share target: source share, text intact", "CLIP-01 API 4",
              got is not None and d.get("text") == text and d.get("source") == "share",
              "" if got else f"no push; am start: {out.strip()[:120]}", latency_ms=(time.monotonic() - t0) * 1000)
    rec.check("the Mac acked it applied (the fake Mac writes and acks like M-APP)", "CLIP-01 API 7",
              got is not None and d.get("clip_id") in s.applied_clips)
    ctx.ui.pause()


CHROME = "com.android.chrome"
CHROME_FIRST_RUN = ("No thanks", "Use without an account", "No Thanks", "Got it", "Skip", "Not now", "Accept & continue",
                    "Yes, I'm in", "No, thanks")


def _serve_png(png: bytes) -> tuple[http.server.ThreadingHTTPServer, int]:
    """The PNG at http://10.0.2.2:<port>/x.png (10.0.2.2 is the host as the emulator sees it)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _chrome_copy_image(ctx, port: int) -> str | None:
    """Opens the PNG in Chrome, long-presses it and taps Copy image; None on success, else why it did not work."""
    adb, ui = ctx.adb, ctx.ui
    adb.shell(f"am force-stop {CHROME}", check=False)
    adb.shell(f"am start -a android.intent.action.VIEW -d http://10.0.2.2:{port}/x.png {CHROME}", check=False)
    size = adb.shell("wm size", check=False)
    try:
        w, h = (int(v) for v in size.split(":")[-1].strip().split("x"))
    except ValueError:
        w, h = 1080, 2400
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:                      # first-run sheets, then the page with the URL bar
        try:
            nodes = ui.dump()
        except Exception as exc:  # noqa: BLE001
            return f"uiautomator dump failed: {exc}"
        if not any(n.package == CHROME for n in nodes):
            time.sleep(1)
            continue
        sheet = [n for n in nodes if n.package == CHROME and n.text in CHROME_FIRST_RUN]
        if sheet:
            ui.tap(sheet[0])
            continue
        if any("x.png" in n.text for n in nodes if n.package == CHROME):
            break
        time.sleep(1)
    else:
        return "Chrome did not show the image page within 40 s"
    time.sleep(1.5)
    for _ in range(3):
        adb.shell(f"input swipe {w // 2} {int(h * 0.545)} {w // 2} {int(h * 0.545)} 900")
        copy = ui.wait(6, text="Copy image")
        if copy is not None:
            ui.tap(copy)
            return None
        adb.shell("input keyevent KEYCODE_BACK", check=False)
    return "Chrome offered no Copy image entry after 3 long presses"


def _phone_to_mac_image(ctx, s) -> None:
    """CLIP-03 phone → Mac: Copy image in Chrome, then the Send Clipboard button; the fake Mac checks the chunks."""
    rec = ctx.rec
    sizes = (300_000, 3_000_000)
    server = None
    try:
        for target in sizes:
            png, side = test_png(target)
            digest = C.b64u(hashlib.sha256(png).digest())
            name = f"PNG image {len(png) / 1e6:.1f} MB phone → Mac through the notification button"
            if server is not None:
                server.shutdown()
            server, port = _serve_png(png)
            try:
                why = _chrome_copy_image(ctx, port)
            except Exception as exc:  # noqa: BLE001 — a driving problem is a SKIP, never a crash
                why = f"{type(exc).__name__}: {exc}"
            if why:
                rec.skip(name, "CLIP-03 phone → Mac, CLIP-01 API 1", f"Chrome could not be driven: {why}")
                ctx.ui.home()
                continue
            ctx.ui.home()
            time.sleep(1)
            mark = s.mark()
            t0 = time.monotonic()
            if not _tap_send_clipboard(ctx):
                rec.check(name, "CLIP-03 phone → Mac", False, "the Send Clipboard action was not found in the shade")
                continue
            got = s.wait(lambda m: m.type == "clipboard" and m.op == "push", 30, after=mark)
            if got is None:
                rec.check(name, "CLIP-03 phone → Mac", False,
                          "no clipboard/push in 30 s after the tap (see the HLBENCH lines in the state dir)")
                ctx.ui.close_notifications()
                continue
            d = got.data or {}
            done = _wait_transfer(s, d.get("clip_id"), 30)
            ms = (time.monotonic() - t0) * 1000
            tr = d.get("transfer") or {}
            problems = []
            if d.get("kind") != "image" or d.get("mime") != "image/png":
                problems.append(f"kind={d.get('kind')} mime={d.get('mime')}")
            if not tr:
                problems.append("no transfer (the text path was used)")
            if d.get("source") != "manual":
                problems.append(f"source={d.get('source')}")
            if (d.get("width"), d.get("height")) != (side, side):
                problems.append(f"size {d.get('width')}x{d.get('height')} != {side}x{side}")
            if tr.get("sha256") != digest:
                problems.append("announced sha256 differs from the served PNG (the phone re-encoded it?)")
            if done is None:
                problems.append("the chunks did not complete in 30 s")
            else:
                if not done["in_order"]:
                    problems.append("chunks out of order")
                if done["sha256"] != digest or done["size"] != len(png):
                    problems.append(f"received {done['size']} B, sha256 matches={done['sha256'] == digest}")
                if done["status"] != "applied":
                    problems.append("the fake Mac rejected the transfer")
            logged = _bench_has_image_read(ctx, d.get("clip_id"))
            if not logged:
                problems.append("no HLBENCH ev=clip_read kind=image for this clip on the phone")
            detail = (f"size={tr.get('size')} B chunks={done['chunks'] if done else '?'} "
                      f"sha256_match={bool(done) and done['sha256'] == digest} {d.get('width')}x{d.get('height')} "
                      f"source={d.get('source')}") + ("; " + "; ".join(problems) if problems else "")
            rec.check(name, "CLIP-03 phone → Mac, CLIP-01 API 1/3", not problems, detail, latency_ms=ms)
            ctx.ui.close_notifications()
    finally:
        if server is not None:
            server.shutdown()
        ctx.adb.shell(f"am force-stop {CHROME}", check=False)
        ctx.ui.home()


def _wait_transfer(s, clip_id: str | None, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if clip_id in s.received_transfers:
            return s.received_transfers[clip_id]
        time.sleep(0.2)
    return None


def _bench_has_image_read(ctx, clip_id: str | None) -> bool:
    """The phone logged clip_read kind=image for this clip (HLBENCH, ids and sizes only)."""
    out = ctx.adb.run("logcat", "-d", "-s", "HLBENCH:I", timeout=30, check=False)
    return any(f"ev=clip_read" in ln and f"clip={clip_id}" in ln and "kind=image" in ln for ln in out.splitlines())


def _chunked(ctx, s) -> None:
    rec = ctx.rec
    big_text = ("HandLive e2e chunked text. " * 8000)[:200_000]
    clip, ack, ms = push_transfer(ctx, s, "text", "text/plain", big_text.encode())
    rec.check("text above CLIP_INLINE_MAX in chunks: ack applied", "CLIP-03 API 3 logic 5, QC5",
              ack is not None and ack.ok and (ack.data or {}).get("status") == "applied", _ack_text(ack),
              latency_ms=ms)
    png, side = test_png(300_000)
    clip, ack, ms = push_transfer(ctx, s, "image", "image/png", png, side, side)
    rec.check(f"PNG image {len(png) // 1000} kB Mac → phone: ack applied", "CLIP-03 steps 6–11",
              ack is not None and ack.ok and (ack.data or {}).get("status") == "applied", _ack_text(ack),
              latency_ms=ms)
    png, side = test_png(5_000_000)
    clip, ack, ms = push_transfer(ctx, s, "image", "image/png", png, side, side)
    rec.check(f"PNG image {len(png) / 1e6:.1f} MB Mac → phone: ack applied", "CLIP-03, QC9",
              ack is not None and ack.ok and (ack.data or {}).get("status") == "applied", _ack_text(ack),
              latency_ms=ms, target_ms=2000)
    clip, ack, ms = push_transfer(ctx, s, "image", "image/png", b"\x89PNG", 64, 64, size=11 * 1024 * 1024,
                                  send_chunks=False)
    rec.check("image over 10 MiB: CLIP_TOO_LARGE before any chunk", "CLIP-03 API 3 logic 1, E2",
              ack is not None and not ack.ok and ack.code == "CLIP_TOO_LARGE"
              and (ack.error.get("details") or {}).get("status") == "rejected", _ack_text(ack))
    png, side = test_png(150_000)
    clip, ack, ms = push_transfer(ctx, s, "image", "image/png", png, side, side, corrupt=True)
    details = (ack.error or {}).get("details") or {} if ack else {}
    rec.check("chunks that do not match the SHA-256: CLIP_CHECKSUM_MISMATCH with the transfer_id",
              "CLIP-03 API 3, E4", ack is not None and not ack.ok and ack.code == "CLIP_CHECKSUM_MISMATCH"
              and details.get("status") == "rejected" and "transfer_id" in details, _ack_text(ack))
    rec.skip("automatic sending on copy (Accessibility service)", "CLIP-01 automatic path",
             "needs the disclosure consent and the Accessibility service turned on in system settings; the "
             "harness covers the manual paths (C15)")
    rec.check("no schema violation in the clipboard messages", "shared/schemas", not s.violations,
              "; ".join(s.violations[:3]))
