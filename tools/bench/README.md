English | [Tiếng Việt](README.vi.md)

# Benchmarks: clipboard, SMS, calls, reconnect time and relay load

These scripts measure the Phase 1 targets of gate G1 and the Phase 2 and Phase 3 targets from timestamped logs of the devices, and load-test the relay:

| Metric | Target | Measured from → to |
|--------|--------|--------------------|
| Text clip (sent inline) | < 50 ms | sender has the content (`clip_read`) → receiver finished writing its clipboard (`clip_applied`); copy detection is shown apart (04-clipboard QC9) |
| Image of about 5 MB | < 2 s | same |
| Reconnect | < 3 s | network up again or Mac woke up (`net`, `wake`) → client back to `Connected` (CONN-02, 00-common-specs 0.11) |
| New SMS notification on the Mac (Phase 2) | < 500 ms on the LAN, ≤ 1 s over the relay | the phone's `ContentObserver` fired (`sms_detected` field `onchange`) → the client posted the notification (`sms_notified`) (SMS-02) |
| Reply confirmed as Sent (Phase 2) | < 2 s | the user pressed Send (`sms_send_tap`) → the client shows Sent (`sms_status_received status=sent`), one device (SMS-04); also the placeholder bubble < 100 ms and the ack < 300 ms on the LAN |
| Call state on the client (Phase 3) | < 200 ms on the LAN, ≤ 1 s over the relay | the phone's OS callback or broadcast behind a change (`call_changed` field `os`) → the client decrypted the `call_event/state` that carried it (`call_state_received`, joined on the envelope id) (CALL-01) |
| Call shown (Phase 3) | ≤ 300 ms | the first RINGING callback → the Mac's panel (`call_panel_shown`) or the iPhone/iPad's in-app banner (`call_banner_shown`) (CALL-01) |
| Answer from the Mac (Phase 3) | < 500 ms end to end | Answer clicked (`call_action_tap action=answer`) → the phone's OFFHOOK callback, and → the Mac received `state = offhook`; Decline and End → the client received `state = idle`, also < 500 ms (CALL-02, CALL-03) |
| Decline from an iPhone/iPad notification (Phase 3) | < 2 s over the relay | `call_action_tap from=notification` → the phone's IDLE callback (CALL-02 B1–B3) |
| Missed-call notification (Phase 3) | ≤ 1.5 s | the phone's IDLE callback of a missed call → `call_missed_notified` (CALL-04) |
| Incoming-call push (Phase 3) | < 300 ms after the number is settled | the first `call_changed settled=true` of the call — the broadcast that brought the number, the second ringing copy without it for a withheld caller, or `RINGING` itself without `READ_CALL_LOG` — or `RINGING` + 300 ms when nothing settled the number within that wait → `call_push_sent status=202`, phone only (CALL-01 API 4 logic 2); display by the extension (`call_push_shown`) without target |
| Relay at 1,000 connections (Phase 2) | no failure, no lost frame | `relay_load.py`: registration, pairing, `/v1/relay`, forwarding latency percentiles |

A target is met when the 95th percentile is under it. Python 3.10+, standard library only — except the relay load test, which needs `requirements-load.txt`.

| File | Purpose |
|------|---------|
| `bench_log.py` | Parses the `HLBENCH/1` lines below |
| `clock_sync.py` | Clock offset between two devices from their request/ack exchanges |
| `clip_latency.py` | Clipboard latency per transfer and per size bucket |
| `reconnect_time.py` | Reconnect time per episode |
| `sms_latency.py` | New SMS notification latency per message and bucket (LAN, relay), reply-to-Sent time per send, placeholder bubble and ack times, push display time |
| `call_latency.py` | Call state delivery per envelope (LAN, relay), panel and banner times, answer, decline and end times, decline from an iPhone/iPad notification, missed-call notifications, push times, and the Focus rule of the Mac's alerts |
| `relay_load.py` | Relay load test: N fake devices through CONN-03 and `/v1/relay` (see "Relay load test") |
| `relay_load_fake.py`, `relay_load_self_test.py` | An in-process stand-in for the relay and the test of `relay_load.py` against it (CI) |
| `requirements-load.txt` | Pinned dependencies of the load test: the vector tools' `cryptography` and PyNaCl, `websockets` (BSD-3-Clause) |
| `collect_logs.sh` | Records one session: Android over `adb logcat`, the Mac through `log stream` |
| `make_test_png.py` | Writes an incompressible PNG of a given size for the image scenarios |
| `self_test.py`, `sms_self_test.py`, `call_self_test.py` | Run the scripts on synthetic logs with known timings (CI runs them) |

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
| `clip_read_failed` | Sender (Android) | A local clip was not sent (CLIP-01 E3, CLIP-03 E2, E3, E10) | `reason` (`empty_or_not_text`, `image_too_large`, `image_unreadable`, `permission_lost`), `stage` (`start`: the system refused to open the read activity; `focus`: no focus within 1 s; `read`: item 0 is neither text nor an image URI; `copy`; `normalize`), `why`, `mimes` (the `ClipDescription` MIME types), `parts` (`text`, `html`, `uri`, `intent` that item 0 carries), `authority` of a `content:` URI (never a path or content), `source` |
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

### Call events (Phase 3)

Privacy as above and as the call functions require: only the random `call_id` and envelope ids, states, the SIM's `sub_id` and error codes — never a number, a contact name, a SIM label or a DTMF digit.

| `ev` | Who | When | Fields |
|------|-----|------|--------|
| `call_changed` | Phone | A-CALL applied an OS event that changed the call context (CALL-01 API 1–3; CALL-04 API 3 for the `end_reason` correction) | `call` (`call_id`), `state` (`ringing`, `offhook`, `idle`), `waiting` (`true`, `false`), `trigger` (`listener`: the state listener, API 2; `broadcast`: the `PHONE_STATE` copy with the number, API 3; `calllog`: the correction), `os` (wall clock, ms, when the OS delivered that callback or broadcast — **start of the state, panel, answer and missed-call latencies**); optional `number` (`known`, `none`: whether the context has the caller's number after the change), `settled` (`true` when this event settled the caller's number: the broadcast that brought it, the second ringing copy without the number key while `READ_CALL_LOG` is granted — a withheld caller, CALL-01 API 3 logic 3 — or `RINGING` itself when `READ_CALL_LOG` is missing; **start of the incoming push time**, CALL-01 API 4 logic 2), `sub` (`sub_id`), `end` (`end_reason` when `idle`) |
| `call_state_sent` | Phone | `call_event/state` handed to one client's session | `call`, `env` (envelope `id`), `peer`, `via` (`lan`, `relay`), `state`, `reason` (`change`: a change of the context; `session`: the current state sent to a new session, CALL-01 E8, not measured) |
| `call_state_received` | Mac, iPhone, iPad | `call_event/state` decrypted — **end of the state latency** | `call`, `env`, `peer`, `state`; optional `waiting` |
| `call_alert` | Mac | M-APP decided how to alert a ringing call (CALL-01 step 7) | `call`, `focus` (`off`, `on`, `unknown`: the Focus status cannot be read yet, `unavailable`: this build cannot ask for it, alerts as `off`), `panel`, `ring` (`true`, `false`), `level` (`passive`, `time_sensitive`, `none`) |
| `call_panel_shown` | Mac | The ringing call panel is on screen (`orderFrontRegardless()` returned) — **end of the panel latency** | `call` |
| `call_banner_shown` | iPhone, iPad | The in-app banner of a ringing call is on screen | `call` |
| `call_notified` | Mac | The incoming-call communication notification was added | `call`, `level` (`passive`, `time_sensitive`) |
| `call_push_sent` | Phone | `POST /v1/push` answered, for an iPhone/iPad without a session | `call`, `peer`, `reason` (`call_incoming`, `call_missed`), `status` (HTTP status) |
| `call_push_shown` | iPhone, iPad (extension) | The extension decrypted a call push and called the content handler | `call`, `reason`, `late` (`true` when more than 60 s after `started_at`, CALL-01 E7) |
| `call_action_tap` | Mac, iPhone, iPad | The user chose Answer, Decline (also Decline with Message…) or End, or the `HL_CALL_REJECT` notification action reached the iPhone/iPad app — **start of the action times** | `call`, `action` (`answer`, `reject`, `end`), `from` (`panel`, `menu`, `notification`, `banner`) |
| `call_action_sent` | Mac, iPhone, iPad | `call_event/action` handed to the WebSocket, one line per attempt (a retry keeps the envelope `id`) | `call`, `env`, `peer`, `action`, `via`, `attempt` |
| `call_action_received` | Phone | `call_event/action` decrypted | `call`, `env`, `peer`, `action` |
| `call_action_ack_sent` | Phone | Its `ack` handed to the WebSocket (once the Telecom method returned, or with the error) | `call`, `env`, `peer`, `ok`; optional `code` |
| `call_action_ack_received` | Mac, iPhone, iPad | That `ack` decrypted | `call`, `env`, `peer`, `ok`; optional `code` |
| `call_missed_notified` | Mac, iPhone, iPad | A missed-call notification was added — **end of the missed-call latency** | `call` (`none` when no call context matched), `source` (`log_new`; `state` without the call log, flow A); optional `entry` (`entry_id`) |
| `app_call_changed` | Phone | A-CALL applied a notification event that changed an app-call context (CALL-05 API 1), the app's own change after an intent included — **start of the app call delivery and panel latencies, end of the app call action times** | `call` (app `call_id`), `state` (`ringing`, `ongoing`, `ended`), `os` (wall clock, ms: the notification's `postTime` for a post, the listener callback for a removal, the moment A-CALL decided otherwise for the end of the link window or a lost listener); optional `end` (`end_reason` with `ended`: `declined`, `ended`, `missed`, `unknown` — the call could no longer be followed: the listener lost, an answer nothing followed, the in-call notification dismissed) |
| `app_call_sent` | Phone | `call_event/app_call` handed to one session | `call`, `env`, `peer`, `via` (`lan`, `relay`), `state`, `reason` (`change`: a change of the context; `session`: the current version sent to a new session, not measured) |
| `app_call_received` | Mac | `call_event/app_call` decrypted — **end of the app call delivery latency** | `call`, `env`, `peer`, `state` |
| `app_call_panel_shown` | Mac | The incoming or in-call panel of an app call came on screen (once per showing) — **end of the app call panel latency** | `call` |
| `app_call_intent_sent` | Phone | HandLive sent the app's PendingIntent (`send` returned) or posted the tap-to-answer notification — **start of the app call action times** | `call`, `action` (`answer`, `reject`, `end`), `mode` (`direct`: the answer intent with the background-start option; `tap`: the tap-to-answer notification posted, the user's tap on the phone sends the intent; `plain`: an intent without the option, for decline and end) |

The Mac's taps, sends and acks of an app call are the `call_action_*` events above, keyed by the app `call_id`; `call_latency.py` tells them apart from cellular calls by that id. Never the app's package name, its label or the caller.

### App call latency rows (Phase 3, CALL-05)

Added to `call_latency.py` output; a target is met when the 95th percentile is under it:

- `app call delivery lan`, `app call delivery relay`: `app_call_changed` field `os` → the Mac's `app_call_received` of the envelope of `app_call_sent reason=change` (joined on `env`), on the phone's clock: 200 ms on the LAN, 1 s over the relay
- `app call shown`: the first `app_call_changed state=ringing` → the first `app_call_panel_shown` of the call, across clocks: ≤ 400 ms (a call that never rang, dialed in the app, is left out)
- `app call decline`, `app call end`: `app_call_intent_sent action=reject` or `end` (`mode=plain`) → the next `app_call_changed state=ended` with `end=declined` or `ended`, phone only: ≤ 500 ms
- `app call answer direct`: `app_call_intent_sent action=answer mode=direct` → the next `app_call_changed state=ongoing`, phone only: ≤ 1 s
- `app call answer tap`: `mode=tap` counted, not timed (the user's tap on the phone notification completes it)
- `app call answer back`, `app call decline back`, `app call end back`: the Mac's `call_action_tap` → its `app_call_received` with the resulting state, one device, no target; only taps whose intent on the phone led to that state

A call that ends without an intent before it (`end=unknown`: the listener lost, the in-call notification dismissed), or that ends otherwise after one, is in no action row; the report lists every intent with what followed it.

```text
HLBENCH/1 wall=1727151101000.000 mono=9001000000000 dev=8c7d6e5f role=android ev=clip_read clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e kind=text bytes=27 source=auto
HLBENCH/1 wall=1727151099770.500 mono=5001004000000 dev=5b1f8c2e role=macos ev=clip_received clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e peer=8c7d6e5f kind=text bytes=27
HLBENCH/1 wall=1727151142000.000 mono=5042000000000 dev=5b1f8c2e role=macos ev=state from=Discovering to=Connected channel=lan
HLBENCH/1 wall=1727150400164.500 mono=9001041000000 dev=8c7d6e5f role=android ev=call_changed call=0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90 state=ringing waiting=false trigger=broadcast os=1727150400163.000 number=known settled=true sub=1
```

## Clocks

The two devices' clocks differ by up to seconds, which is far more than 50 ms. Every `clipboard/push`, `sms/send` and `call_event/action` is acknowledged and both sides log the four moments (an `sms/send` or `call_event/action` that was retried is left out), so `clock_sync.py` computes the offset as NTP does (RFC 5905 §8): `offset = ((t2 − t1) + (t3 − t4)) / 2`, error at most half the network round trip. For each measurement it takes the exchange with the smallest round trip within ±120 s (`--window-s`), so a slow drift during the session does not matter; a device two hops away (an iPad that gets clips through the phone) is reached through the phone. A session without any clip (for example only Wi-Fi toggles on the phone) has no exchange: copy one short text each way at its start, or pass `--offset A:B=MS` (clock of B minus clock of A); otherwise the offset is assumed 0 and the report says so. A session with only calls gets its offsets from the call actions: decline one test call from the Mac (and one from the iPhone) at its start. Keep automatic network time on for every device anyway.

## Running

```sh
tools/bench/collect_logs.sh bench-logs/pixel8-mbp [adb-serial]   # record, Ctrl-C to stop
python3 tools/bench/clip_latency.py bench-logs/pixel8-mbp/*.log   # add --json for the report, --check for exit 1 on a miss
python3 tools/bench/reconnect_time.py bench-logs/pixel8-mbp/*.log
python3 tools/bench/sms_latency.py bench-logs/pixel8-mbp/*.log     # --json, --check as above
python3 tools/bench/call_latency.py bench-logs/pixel8-mbp/*.log    # --json, --check as above
python3 tools/bench/make_test_png.py 5000000 image-5mb.png         # test image of about 5 MB
python3 tools/bench/self_test.py                                   # must print "0 failed"
```

`clip_latency.py` prints one row per transfer (latency, copy detection, and its split into sender, network and receiver time), the clips that were read but never applied (refused as a conflict, lost, or the other log is missing), and a summary per bucket: text inline (≤ 180 KiB, target 50 ms), text chunked, images below 4.5 MB, about 5 MB (4.5–5.5 MB, target 2 s) and above. `reconnect_time.py` prints one row per episode with its trigger (`net up on <dev>`, `wake on <dev>`, or `loss` when nothing on the network changed) and the target check.

`sms_latency.py` prints one row per notified message (latency on the phone's clock and its split: detection, phone, network, client), the incoming messages sent to a client that never notified (setting off, conversation open, lost), one row per reply (attempts, final status, time to Sent, bubble, ack, radio time on the phone, error code), the push display times, and a summary with median, p95 and maximum: `notification lan` (target 500 ms), `notification relay` (1 s), `reply sent` (2 s), `placeholder bubble` (100 ms), `ack lan` (300 ms, sends without a retry), `push shown` (no target). The reply time needs no clock offset (one device); the notification latency does — send one reply at the start of the session, or pass `--offset`.

`call_latency.py` prints one row per state envelope (latency on the phone's clock, its trigger, and the split into phone and network time), the envelopes never received, the panel and banner times, one row per action (source, transport, attempts, ack, tap → the phone's callback, tap → the resulting state on the client, ack time, error code), the missed-call notifications, the pushes (HTTP status, time after the number, display by the extension), the Mac alerts that break the Focus rule (Focus on: no panel, no ringtone, a time-sensitive notification; Focus status not readable: the panel without ringtone; a panel always with a passive notification), and a summary: `state lan` (200 ms), `state relay` (1 s), `shown panel` and `shown banner` (300 ms), `answer to phone offhook`, `answer back on client`, `decline back on client`, `end back on client` (500 ms), `decline from notification` (2 s), `missed notification` (1.5 s), `incoming push` (300 ms), `push shown` (no target). With app calls it also prints the app call envelopes never received, one row per app call envelope, the app call panel times, every intent the phone sent with what followed it, one row per tap on an app call (the mode of the phone's intent, tap → the result back on the Mac, ack), and the rows above. `--check` also fails on a Focus rule problem. Tap → the state back on the client needs no clock offset; the other times do.

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
| C1 | Phase 3: a call from another phone, the Mac on the LAN, no Focus: panel and ringtone; let it ring 5 s, then decline on the phone (start with one decline from the Mac for the clock offset) | 20 |
| C2 | Phase 3: answer from the Mac panel (Return), talk 10 s on the phone, end from the Mac panel | 10 |
| C3 | Phase 3: decline from the Mac panel (⌘⌫); twice with Decline with Message… and a template | 10 + 2 |
| C4 | Phase 3: call waiting (CALL-01 E9): during a call answered on the phone, a call from a third phone: the Mac shows the waiting caller as information only, End hidden, no push to an iPhone; decline the waiting call on the phone | 3 |
| C5 | Phase 3: two SIMs: call each SIM of a dual-SIM phone; the panel and the notification show the right SIM label (`sub` of `call_changed`) | 3 + 3 |
| C6 | Phase 3: a Focus on the Mac: no panel, no ringtone, a time-sensitive notification, the call in the menu bar menu; then with the Focus status permission not granted: the panel without ringtone | 3 + 2 |
| C7 | Phase 3: AirPods connected to the phone: C1 and C2 again; the audio stays on the phone or the AirPods (no effect in this phase) | 3 |
| C8 | Phase 3: iPhone with HandLive in the background (no session), the phone reachable through the relay: the incoming-call push, then Decline from the notification (unlock) | 10 |
| C9 | Phase 3: a missed call (let it ring out) with the Mac connected; then with the iPhone in the background, where the missed-call push replaces the incoming one | 5 + 3 |
| C10 | Phase 3: iPhone with HandLive open: the in-app banner, Decline from the banner | 5 |
| AC1 | Phase 3 (CALL-05): Telegram on the phone calls the Mac user; the Mac panel appears with the app name and caller within 400 ms | 10 |
| AC2 | Phase 3: decline or end the Telegram call from the Mac panel; the phone's Telegram is notified within 500 ms | 5 + 5 |
| AC3 | Phase 3: answer a Telegram call from the Mac panel with the Accessibility service on (direct mode); the phone's Telegram goes into-call within 1 s | 5 |
| AC3.3 | Phase 3: answer a Telegram call with the Accessibility service off (tap mode); "Tap the notification on your phone to answer." appears on the Mac | 5 |
| AC5 | Phase 3: verify in `logs | grep caller` that no caller names leave the phone | — |
| AC6 | Phase 3: Notification access off: "Calls from Other Apps" card is "Needs permission"; cellular calls (C1–C10) unaffected | 1 |

Then stop the recording, run both scripts and fill a row per pair (p95 in ms; add the `--json` output to the report):

| Phone (Android) | Mac (macOS) | Text phone → Mac | Text Mac → phone | Image 5 MB phone → Mac | Image 5 MB Mac → phone | Reconnect (R1–R4) | Not applied | Notes |
|-----------------|-------------|------------------|------------------|------------------------|------------------------|-------------------|-------------|-------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

Phase 2 adds a row per pair from `sms_latency.py` (p95 in ms):

| Phone (Android) | Client | Notification LAN (S1) | Notification relay (S2) | Reply Sent (S3) | Bubble | Ack LAN | Not notified | Notes |
|-----------------|--------|-----------------------|-------------------------|-----------------|--------|---------|--------------|-------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

Phase 3 adds a row per pair from `call_latency.py` (p95 in ms):

| Phone (Android) | Client | State LAN (C1) | Panel (C1) | Answer → offhook (C2) | Answer back (C2) | Decline back (C3) | End back (C2) | Decline from notification (C8) | Missed (C9) | Push (C8) | Focus rule (C6) | Notes |
|-----------------|--------|----------------|------------|-----------------------|------------------|-------------------|---------------|--------------------------------|-------------|-----------|-----------------|-------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | | | | | |

A pair passes when every p95 is under its target and "Not applied" lists only clips the scenario expected to be refused. Record devices that block the Accessibility service or `ClipboardReadActivity` in `docs/deployment-guide.md` (phase 1 risks).
