English | [Tiếng Việt](README.vi.md)

# Benchmarks: clipboard, SMS, reconnect time and relay load

These scripts measure the Phase 1 targets of gate G1 and the Phase 2 targets from timestamped logs of the devices, and load-test the relay:

| Metric | Target | Measured from → to |
|--------|--------|--------------------|
| Text clip (sent inline) | < 50 ms | sender has the content (`clip_read`) → receiver finished writing its clipboard (`clip_applied`); copy detection is shown apart (04-clipboard QC9) |
| Image of about 5 MB | < 2 s | same |
| Reconnect | < 3 s | network up again or Mac woke up (`net`, `wake`) → client back to `Connected` (CONN-02, 00-common-specs 0.11) |
| New SMS notification on the Mac (Phase 2) | < 500 ms on the LAN, ≤ 1 s over the relay | the phone's `ContentObserver` fired (`sms_detected` field `onchange`) → the client posted the notification (`sms_notified`) (SMS-02) |
| Reply confirmed as Sent (Phase 2) | < 2 s | the user pressed Send (`sms_send_tap`) → the client shows Sent (`sms_status_received status=sent`), one device (SMS-04); also the placeholder bubble < 100 ms and the ack < 300 ms on the LAN |
| Relay at 1,000 connections (Phase 2) | no failure, no lost frame | `relay_load.py`: registration, pairing, `/v1/relay`, forwarding latency percentiles |

A target is met when the 95th percentile is under it. Python 3.10+, standard library only — except the relay load test, which needs `requirements-load.txt`.

| File | Purpose |
|------|---------|
| `bench_log.py` | Parses the `HLBENCH/1` lines below |
| `clock_sync.py` | Clock offset between two devices from their request/ack exchanges |
| `clip_latency.py` | Clipboard latency per transfer and per size bucket |
| `reconnect_time.py` | Reconnect time per episode |
| `sms_latency.py` | New SMS notification latency per message and bucket (LAN, relay), reply-to-Sent time per send, placeholder bubble and ack times, push display time |
| `relay_load.py` | Relay load test: N fake devices through CONN-03 and `/v1/relay` (see "Relay load test") |
| `relay_load_fake.py`, `relay_load_self_test.py` | An in-process stand-in for the relay and the test of `relay_load.py` against it (CI) |
| `requirements-load.txt` | Pinned dependencies of the load test: the vector tools' `cryptography` and PyNaCl, `websockets` (BSD-3-Clause) |
| `collect_logs.sh` | Records one session: Android over `adb logcat`, the Mac through `log stream` |
| `make_test_png.py` | Writes an incompressible PNG of a given size for the image scenarios |
| `self_test.py`, `sms_self_test.py` | Run the scripts on synthetic logs with known timings (CI runs them) |

## Log line format `HLBENCH/1`

Both apps write one line per event, in **debug builds only** (release builds never emit them):

- Android: `Log.i("HLBENCH", line)`.
- macOS: `Logger(subsystem: "app.handlive.mac", category: "bench").info("\(line, privacy: .public)")` — without `.public` the unified log hides the values. iOS/iPadOS (Phase 2): subsystem `app.handlive.ios`; the notification service extension `app.handlive.ios.nse`.

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

### SMS events (Phase 2)

Privacy as above: only the provider's `message_key` (`sms:<_id>`), the random `local_id`, states and error codes — never the text, the number or a name.

| `ev` | Who | When | Fields |
|------|-----|------|--------|
| `sms_detected` | Phone | A-SMS read a new row it will broadcast (SMS-02 steps 3–4) | `msg` (`message_key`), `box` (`inbox`, `sent`, `failed`), `onchange` (wall clock, ms, of the first `ContentObserver.onChange` of the coalesced batch — **start of the notification latency**); optional `provider` (the row's `date`, ms) |
| `sms_new_sent` | Phone | `sms/new` handed to one client's session | `msg`, `peer`, `via` (`lan`, `relay`) |
| `sms_new_received` | Mac, iPhone, iPad | `sms/new` decrypted | `msg`, `peer` |
| `sms_notified` | Mac, iPhone, iPad | `UNUserNotificationCenter.add` completed without error — **end of the notification latency**; not logged when no notification is due (SMS-02 step 7) | `msg` |
| `sms_push_sent` | Phone | `POST /v1/push` answered 202 for an iPhone/iPad without a session | `msg`, `peer` |
| `sms_push_shown` | iPhone, iPad (extension) | The extension decrypted the push and called the content handler | `msg` |
| `sms_send_tap` | Mac, iPhone, iPad | Send pressed in a conversation or New Message, or a quick reply submitted — **start of the reply time** | `local` (`local_id`) |
| `sms_bubble` | Mac, iPhone, iPad | The placeholder bubble is on screen | `local` |
| `sms_send_sent` | Mac, iPhone, iPad | `sms/send` handed to the WebSocket, one line per attempt | `local`, `peer`, `attempt` (1, 2…), `via` (`lan`, `relay`) |
| `sms_send_received` | Phone | `sms/send` decrypted | `local`, `peer` |
| `sms_send_ack_sent` | Phone | Its `ack` handed to the WebSocket | `local`, `peer`, `ok` (`true`, `false`); optional `code` (error code) |
| `sms_send_ack_received` | Mac, iPhone, iPad | That `ack` decrypted | `local`, `peer`, `ok`; optional `code` |
| `sms_radio_done` | Phone | Every part reported by `SmsManager` (sent intents) | `local`, `result` (`sent`, `failed`); optional `code` |
| `sms_status_sent` | Phone | `sms/status` handed to the WebSocket | `local`, `peer`, `status` (`sending`, `sent`, `delivered`, `failed`); optional `code` |
| `sms_status_received` | Mac, iPhone, iPad | The status applied to the outbox and shown — **end of the reply time** when `status=sent` | `local`, `status`; optional `code` |

```text
HLBENCH/1 wall=1727151101000.000 mono=9001000000000 dev=8c7d6e5f role=android ev=clip_read clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e kind=text bytes=27 source=auto
HLBENCH/1 wall=1727151099770.500 mono=5001004000000 dev=5b1f8c2e role=macos ev=clip_received clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e peer=8c7d6e5f kind=text bytes=27
HLBENCH/1 wall=1727151142000.000 mono=5042000000000 dev=5b1f8c2e role=macos ev=state from=Discovering to=Connected channel=lan
```

## Clocks

The two devices' clocks differ by up to seconds, which is far more than 50 ms. Every `clipboard/push` and every `sms/send` is acknowledged and both sides log the four moments (an `sms/send` that was retried is left out), so `clock_sync.py` computes the offset as NTP does (RFC 5905 §8): `offset = ((t2 − t1) + (t3 − t4)) / 2`, error at most half the network round trip. For each measurement it takes the exchange with the smallest round trip within ±120 s (`--window-s`), so a slow drift during the session does not matter; a device two hops away (an iPad that gets clips through the phone) is reached through the phone. A session without any clip (for example only Wi-Fi toggles on the phone) has no exchange: copy one short text each way at its start, or pass `--offset A:B=MS` (clock of B minus clock of A); otherwise the offset is assumed 0 and the report says so. Keep automatic network time on for every device anyway.

## Running

```sh
tools/bench/collect_logs.sh bench-logs/pixel8-mbp [adb-serial]   # record, Ctrl-C to stop
python3 tools/bench/clip_latency.py bench-logs/pixel8-mbp/*.log   # add --json for the report, --check for exit 1 on a miss
python3 tools/bench/reconnect_time.py bench-logs/pixel8-mbp/*.log
python3 tools/bench/sms_latency.py bench-logs/pixel8-mbp/*.log     # --json, --check as above
python3 tools/bench/make_test_png.py 5000000 image-5mb.png         # test image of about 5 MB
python3 tools/bench/self_test.py                                   # must print "0 failed"
```

`clip_latency.py` prints one row per transfer (latency, copy detection, and its split into sender, network and receiver time), the clips that were read but never applied (refused as a conflict, lost, or the other log is missing), and a summary per bucket: text inline (≤ 180 KiB, target 50 ms), text chunked, images below 4.5 MB, about 5 MB (4.5–5.5 MB, target 2 s) and above. `reconnect_time.py` prints one row per episode with its trigger (`net up on <dev>`, `wake on <dev>`, or `loss` when nothing on the network changed) and the target check.

`sms_latency.py` prints one row per notified message (latency on the phone's clock and its split: detection, phone, network, client), the incoming messages sent to a client that never notified (setting off, conversation open, lost), one row per reply (attempts, final status, time to Sent, bubble, ack, radio time on the phone, error code), the push display times, and a summary with median, p95 and maximum: `notification lan` (target 500 ms), `notification relay` (1 s), `reply sent` (2 s), `placeholder bubble` (100 ms), `ack lan` (300 ms, sends without a retry), `push shown` (no target). The reply time needs no clock offset (one device); the notification latency does — send one reply at the start of the session, or pass `--offset`.

## Relay load test

`relay_load.py` drives N fake devices (default 1,000) through the relay exactly as the apps do: `POST /v1/devices` (`HLREG1`), `POST /v1/auth/challenge` + `/v1/auth/token` (`HLAUTH1`) — the messages and Ed25519 signatures come from `tools/vectors/handlive_protocol_derivations.py`, the code behind `test-vectors/relay-auth.json` — then `POST /v1/pairs` for devices 2k (android) and 2k+1 (macos/ios) with the 0.6.2 attestation signed by both, and `/v1/relay`. Once every device is connected, each sends `--frames` frames to its peer every `--interval-ms` — text wrappers, alternating with binary `HR` frames with `--binary` — and the peer's side of the same process timestamps them (one monotonic clock). The report lists failures per step (HTTP status and error code), relay `error` ops, unexpected WebSocket closes, frames lost, and p50/p95/p99/max of registration, connection and forwarding; `--check` exits 1 on any of them; `--cleanup` removes the devices afterwards (`DELETE /v1/devices/me?revoke_pairs=false`).

```sh
tools/.venv/bin/python -m pip install -r tools/bench/requirements-load.txt
RELAY_TRUSTED_PROXIES=127.0.0.1 …relay-server        # so the per-device X-Forwarded-For counts (10 registrations/hour/IP)
tools/.venv/bin/python tools/bench/relay_load.py --relay http://127.0.0.1:8080 --devices 1000 --frames 10 --binary --cleanup --check
tools/.venv/bin/python tools/bench/relay_load_self_test.py   # against the in-process fake relay (CI)
```

Each connection needs a file descriptor on both sides: start the relay with `ulimit -n` of a few thousand (the script raises its own limit). To check that idle connections survive the relay's 45 s idle timeout through WebSocket pings alone, space the frames more than 45 s apart (`--frames 3 --interval-ms 50000`).

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
| S1 | Phase 2: send an SMS to the phone from another phone while the Mac shows no conversation (LAN) | 20 |
| S2 | Phase 2: same as S1 with the Mac on another network (internet connection, relay) | 10 |
| S3 | Phase 2: reply from the Mac's Messages window with normal signal (start with one reply for the clock offset) | 20 |
| S4 | Phase 2: quick reply from the notification on the Mac; then from an iPhone with HandLive in the background | 5 + 5 |

Then stop the recording, run both scripts and fill a row per pair (p95 in ms; add the `--json` output to the report):

| Phone (Android) | Mac (macOS) | Text phone → Mac | Text Mac → phone | Image 5 MB phone → Mac | Image 5 MB Mac → phone | Reconnect (R1–R4) | Not applied | Notes |
|-----------------|-------------|------------------|------------------|------------------------|------------------------|-------------------|-------------|-------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

Phase 2 adds a row per pair from `sms_latency.py` (p95 in ms):

| Phone (Android) | Client | Notification LAN (S1) | Notification relay (S2) | Reply Sent (S3) | Bubble | Ack LAN | Not notified | Notes |
|-----------------|--------|-----------------------|-------------------------|-----------------|--------|---------|--------------|-------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

A pair passes when every p95 is under its target and "Not applied" lists only clips the scenario expected to be refused. Record devices that block the Accessibility service or `ClipboardReadActivity` in `docs/deployment-guide.md` (phase 1 risks).
