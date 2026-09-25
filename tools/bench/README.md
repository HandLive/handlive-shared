English | [Tiếng Việt](README.vi.md)

# Benchmarks: clipboard latency and reconnect time

These scripts measure the Phase 1 targets of gate G1 from timestamped logs of both devices:

| Metric | Target | Measured from → to |
|--------|--------|--------------------|
| Text clip (sent inline) | < 50 ms | sender has the content (`clip_read`) → receiver finished writing its clipboard (`clip_applied`); copy detection is shown apart (04-clipboard QC9) |
| Image of about 5 MB | < 2 s | same |
| Reconnect | < 3 s | network up again or Mac woke up (`net`, `wake`) → client back to `Connected` (CONN-02, 00-common-specs 0.11) |

A target is met when the 95th percentile is under it. Python 3.10+, standard library only.

| File | Purpose |
|------|---------|
| `bench_log.py` | Parses the `HLBENCH/1` lines below |
| `clock_sync.py` | Clock offset between two devices from their request/ack exchanges |
| `clip_latency.py` | Clipboard latency per transfer and per size bucket |
| `reconnect_time.py` | Reconnect time per episode |
| `collect_logs.sh` | Records one session: Android over `adb logcat`, the Mac through `log stream` |
| `make_test_png.py` | Writes an incompressible PNG of a given size for the image scenarios |
| `self_test.py` | Runs the scripts on synthetic logs with known timings (CI runs it) |

## Log line format `HLBENCH/1`

Both apps write one line per event, in **debug builds only** (release builds never emit them):

- Android: `Log.i("HLBENCH", line)`.
- macOS: `Logger(subsystem: "app.handlive.mac", category: "bench").info("\(line, privacy: .public)")` — without `.public` the unified log hides the values. iOS/iPadOS (Phase 2): subsystem `app.handlive.ios`.

```text
HLBENCH/1 wall=<ms> mono=<ns> dev=<id8> role=<android|macos|ios> ev=<event> [<key>=<value> ...]
```

| Field | Value |
|-------|-------|
| `wall` | Wall clock of the device, ms since the Unix epoch, up to 3 decimals (Android `System.currentTimeMillis()`; Apple `Date().timeIntervalSince1970 * 1000`) |
| `mono` | Monotonic clock that keeps counting during sleep, ns (Android `SystemClock.elapsedRealtimeNanos()`; Apple `clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)`). Optional but recommended: intervals on one device use it |
| `dev` | First 8 hex digits of the device's `device_id` |
| `role` | `android`, `macos` or `ios` |
| `ev` | One of the events below |

Values never contain spaces. Anything before the marker `HLBENCH/1 ` (logcat or `log stream` prefixes) is ignored. Privacy (QC2, 0.6.5): never the clipboard content, device or contact names or addresses — only the random `clip_id`, kinds, sizes and states.

| `ev` | Who | When | Fields |
|------|-----|------|--------|
| `copy_detected` | Sender | Copy signal seen, before reading: Android Accessibility copy event or `OnPrimaryClipChangedListener`; Mac `changeCount` change seen by the poll | — |
| `clip_read` | Sender | Content in memory, ready to encrypt (text read, image normalized) — **start of the latency** | `clip`, `kind` (`text`, `image`), `bytes` (UTF-8 bytes of the text, bytes of the normalized image), `source` (`auto`, `manual`, `share`, `mac`) |
| `clip_sent` | Sender | `clipboard/push` handed to the WebSocket, one line per peer (also when the phone forwards a clip, QC6) | `clip`, `peer` |
| `clip_received` | Receiver | `clipboard/push` decrypted | `clip`, `peer` (the device it came from), `kind`, `bytes` |
| `clip_applied` | Receiver | System clipboard write returned; for chunked content after the last chunk was verified — **end of the latency** | `clip` |
| `ack_sent` | Receiver | `ack` of that push handed to the WebSocket | `clip`, `peer`, `status` (`applied`, `ignored`, `rejected`) |
| `ack_received` | Sender | That `ack` decrypted | `clip`, `peer`, `status` |
| `state` | Mac, iPhone, iPad | Every transition of the 0.11 state machine | `to` (`Idle`, `Discovering`, `ConnectingLAN`, `ConnectingRelay`, `Handshaking`, `WaitingPeer`, `Connected`, `Backoff`); optional `from`; `channel` (`lan`, `relay`, `usb`) with `Connected` |
| `net` | Any | OS network change: Android `ConnectivityManager.NetworkCallback`, Apple `NWPathMonitor` | `change`: `up` (a network is available), `down` (lost), `changed` (default network switched) |
| `wake` | Mac | `NSWorkspace.didWakeNotification` | — |

```text
HLBENCH/1 wall=1727151101000.000 mono=9001000000000 dev=8c7d6e5f role=android ev=clip_read clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e kind=text bytes=27 source=auto
HLBENCH/1 wall=1727151099770.500 mono=5001004000000 dev=5b1f8c2e role=macos ev=clip_received clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e peer=8c7d6e5f kind=text bytes=27
HLBENCH/1 wall=1727151142000.000 mono=5042000000000 dev=5b1f8c2e role=macos ev=state from=Discovering to=Connected channel=lan
```

## Clocks

The two devices' clocks differ by up to seconds, which is far more than 50 ms. Every `clipboard/push` is acknowledged and both sides log the four moments, so `clock_sync.py` computes the offset as NTP does (RFC 5905 §8): `offset = ((t2 − t1) + (t3 − t4)) / 2`, error at most half the network round trip. For each measurement it takes the exchange with the smallest round trip within ±120 s (`--window-s`), so a slow drift during the session does not matter; a device two hops away (an iPad that gets clips through the phone) is reached through the phone. A session without any clip (for example only Wi-Fi toggles on the phone) has no exchange: copy one short text each way at its start, or pass `--offset A:B=MS` (clock of B minus clock of A); otherwise the offset is assumed 0 and the report says so. Keep automatic network time on for every device anyway.

## Running

```sh
tools/bench/collect_logs.sh bench-logs/pixel8-mbp [adb-serial]   # record, Ctrl-C to stop
python3 tools/bench/clip_latency.py bench-logs/pixel8-mbp/*.log   # add --json for the report, --check for exit 1 on a miss
python3 tools/bench/reconnect_time.py bench-logs/pixel8-mbp/*.log
python3 tools/bench/make_test_png.py 5000000 image-5mb.png         # test image of about 5 MB
python3 tools/bench/self_test.py                                   # must print "0 failed"
```

`clip_latency.py` prints one row per transfer (latency, copy detection, and its split into sender, network and receiver time), the clips that were read but never applied (refused as a conflict, lost, or the other log is missing), and a summary per bucket: text inline (≤ 180 KiB, target 50 ms), text chunked, images below 4.5 MB, about 5 MB (4.5–5.5 MB, target 2 s) and above. `reconnect_time.py` prints one row per episode with its trigger (`net up on <dev>`, `wake on <dev>`, or `loss` when nothing on the network changed) and the target check.

## Manual test on the device matrix

Devices (implementation plan §5): Android — Pixel 8 (Android 14 or 15), Galaxy S22/S23 (Android 14), Xiaomi or OPPO (Android 13); Mac — Apple silicon on macOS 26, Intel on macOS 13 or 14. Gate G1 needs at least the Pixel, the Samsung and one Mac; run every phone with both Macs when they are available.

Preparation, once per pair:

1. Install debug builds with bench logging on both devices; pair them (PAIR-01); both on the same 5 GHz Wi-Fi network, automatic network time on.
2. Android: Accessibility auto-send on (CLIP-01), battery optimization exemption granted (SET-01). Mac: on power, "Paste from Other Apps" allowed on macOS 15.4+.
3. Write down the phone model, Android version, Mac model, macOS version and both build numbers.
4. Start `tools/bench/collect_logs.sh bench-logs/<phone>-<mac>` and keep it running for the whole pair.

Scenarios (3 s pause between repetitions):

| # | Scenario | Repeat |
|---|----------|--------|
| T1 | Phone → Mac, auto-send: copy a 20–100 character text in Chrome, paste on the Mac | 20 |
| T2 | Mac → phone: copy a 20–100 character text in TextEdit, paste on the phone | 20 |
| T3 | Phone → Mac, manual: copy, then "Send Clipboard" on the notification (and once with the Quick Settings tile) | 5 |
| T4 | Text of about 200 KiB (chunked) in each direction — recorded, no target | 1 + 1 |
| I1 | 5 MB image (`make_test_png.py 5000000`), phone → Mac and Mac → phone: open it, copy, paste | 5 + 5 |
| I2 | 1 MB and 10 MB images in each direction; an 11 MB image must be refused with "Image is too large (up to 10 MB)" | 1 each |
| R1 | Mac Wi-Fi off, wait 5 s, on | 5 |
| R2 | Mac switches between two SSIDs of the same LAN (for example the 2.4 and 5 GHz bands of one router) | 5 |
| R3 | Phone Wi-Fi off, wait 5 s, on (copy one text each way first, for the clock offset) | 5 |
| R4 | Mac sleeps (lid closed 30 s) and wakes | 3 |
| R5 | Phone screen off for 5 minutes (Doze), then copy on the Mac — must arrive; recorded, no target | 2 |

Then stop the recording, run both scripts and fill a row per pair (p95 in ms; add the `--json` output to the report):

| Phone (Android) | Mac (macOS) | Text phone → Mac | Text Mac → phone | Image 5 MB phone → Mac | Image 5 MB Mac → phone | Reconnect (R1–R4) | Not applied | Notes |
|-----------------|-------------|------------------|------------------|------------------------|------------------------|-------------------|-------------|-------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

A pair passes when every p95 is under its target and "Not applied" lists only clips the scenario expected to be refused. Record devices that block the Accessibility service or `ClipboardReadActivity` in `docs/deployment-guide.md` (phase 1 risks).
