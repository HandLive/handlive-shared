English | [Tiếng Việt](README.vi.md)

# End-to-end harness: the real Android app against a fake Mac

The harness tests the Android app on an emulator, not only with unit tests. A Python "fake Mac" talks to the real app exactly as the Mac app does: PIN pairing, the pinned TLS connection, the session handshake, the capability exchange and every encrypted envelope. adb drives the phone: it taps through the UI, rings the phone from the emulator's modem and sends it SMS. Each step prints PASS or FAIL with its latency and the spec section it checks.

There is no Xcode on the build machine, so the Mac and iPhone apps cannot run here. The fake Mac stands in for them.

## What it covers

| Scenario | Checks | Specs |
|----------|--------|-------|
| `setup` | Install the APK. First run through the UI: welcome, notification primer and dialog, the `connectedDevice` service, the battery exemption. PIN pairing: a wrong PIN and "2 attempts left", a Mac that connects before the PIN is typed, the Security Code on both sides. First session: handshake time, the phone's capability, "Connected to …", one session per pair (4409), `PAIR_UNKNOWN`, 4408, 4411 | SET-01 A, PAIR-01 A1–A5, PAIR-02, CONN-01, CONN-02 |
| `clipboard` | Mac → phone text, duplicate and resent pushes, chunked text, PNG images of 300 kB and 5 MB, `CLIP_TOO_LARGE`, `CLIP_CHECKSUM_MISMATCH`; text with `html` (applied, then returned by Send Clipboard in the sanitized form of `test-vectors/clipboard-html.json`) and `BAD_REQUEST` for `html` with a `transfer` or on an image (all three SKIP when the phone does not list `text/html`). Phone → Mac without Accessibility: the Send Clipboard button (it also proves the Mac's text reached the phone's clipboard) and the Share target; phone → Mac PNG images of 0.3 MB and 3 MB (Chrome Copy image from a host-served page, then Send Clipboard; the fake Mac checks chunk order, size, SHA-256 and the image dimensions; SKIP when Chrome cannot be driven) | CLIP-01…03 |
| `sms` | The permission grant and the capability update. `sms/new` from the modem. First sync with paging over 180 KiB, catch-up sync, cursor errors. `sms/history` paging. `sms/send` with forward-only `sms/status`, the Sent row with `local_id`, deduplication, the send errors. `sms/read_changed`. A revoked `READ_SMS` and the suggestion notification | SMS-01…05, SET-01 B |
| `calls` | A ringing call with a fake contact's name. Answer, decline and end from the Mac, checked against Android's own call state. `CALL_HFP_REQUIRED`, `CALL_ACTION_NOT_ALLOWED`, `CALL_NOT_FOUND`. A reconnect during a call. A waiting call when the modem presents one. `log_new` for answered, declined and missed calls. `log_sync` paging and a bad cursor. Then `tools/bench/call_latency.py` on the run | CALL-01…04 |
| `all` | `setup clipboard sms calls` in that order | |
| `relay` | Needs the local relay stack (`relay_stack/`) and the app built for it. A second fake Mac registers with the relay before it pairs; the phone registers the pair. The LAN goes away (the forward is removed, the session dropped without `session/bye`); the phone must come to `/v1/relay`. Then through the relay: the session handshake, a ringing call, answer and end, a new SMS, `sms/sync` and a reply | CONN-03, PAIR-01 API 8, PAIR-02 API 1 |
| `push` | Same stack. A fake iPhone registers an APNs token, pairs, says goodbye and stays off. An incoming SMS and a ringing call must reach the mock APNs (`sms_new`, `call_incoming`); `hl` opens with the pair's `K_push`. The iPhone then declines through the relay; a second call the caller gives up sends `call_missed` with the same collapse id | CONN-04, SMS-02 step 10, CALL-01 step 5, CALL-02 B1–B3, CALL-04 API 5 |

Every message sent and received is checked against `shared/schemas`. The crypto comes from `tools/vectors`, the code behind the test vectors.

## What it cannot test

- A real Mac, iPhone or iPad: their UI, notifications, Keychain, `NSPasteboard`, HFP. The fake Mac only does what the protocol needs.
- mDNS discovery: the emulator's network carries no multicast. The client dials the forwarded port, like the Mac's `last_host` fast path.
- Apple's and Google's push services: the `push` scenario stops at the mock APNs of `relay_stack/`. The relay stage also needs the app built for the local relay with the two debug patches of `relay_stack/`.
- Automatic clipboard sending through the Accessibility service.
- A waiting call on Android 11 and later: the emulator's modem simulator does not present a second call during an active one.
- Device timings. An emulator on a busy host is not a phone; latencies show trends, not the targets of gate G1.

## Running

```sh
# once: the venv and the debug APK (built from the android repository)
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/e2e/requirements.txt
(cd ../android && ./gradlew :app:assembleFossDebug)

# an emulator with a window, so you can watch the steps
$ANDROID_HOME/emulator/emulator -avd hl-e2e-api35 -no-audio -gpu host -no-snapshot -port 5556 &

tools/.venv/bin/python tools/e2e/e2e.py all --serial emulator-5556 \
    --apk ../android/app/build/outputs/apk/foss/debug/app-foss-debug.apk
tools/.venv/bin/python tools/e2e/e2e.py calls --serial emulator-5556 --step-delay 0   # fast, reuses the pair
```

| Option | Default | Use |
|--------|---------|-----|
| `--serial` | `emulator-5556` | The emulator; every adb call uses `-s` |
| `--apk` | none | Reinstall the app in `setup` and pair again; without it `setup` keeps the app and its pair |
| `--state-dir` | `$HL_E2E_STATE_DIR` or `<tmp>/handlive-e2e/<serial>` | Pair state, logs and results. It holds test keys: keep it out of the repository |
| `--host-port` | 47800 + port − 5500 | The host end of `adb forward` to the phone's port 47800 |
| `--step-delay` | 1 s | Pause after each visible action; 0 for fast runs |
| `--shared-device` | off | Other clients use this emulator: refuse `--apk` and skip the permission revoke (it restarts the app) |
| `--lock-dir` | the workspace's `.locks` | Each scenario takes `<lock-dir>/<serial>` (waits for it, a lock older than 30 minutes is stale) |
| `--relay-state` | `$HANDLIVE_RELAY_STACK_DIR` or `<tmp>/handlive-relay-stack` | The state directory of `relay_stack.py up` (for `relay` and `push`) |

The run prints one line per step and a summary. It exits 1 when a step failed. The state directory keeps:

- `results.json`: every step with its status, detail and latency;
- `hlbench-mac.log` and `logcat-hlbench.log`: the `HLBENCH/1` lines of the fake Mac (`role=macos`) and of the phone, for `tools/bench/*.py`;
- `call_latency.txt`: the report of `tools/bench/call_latency.py`;
- `pair-macos.json`: the fake Mac's keys and pair (mode 0600).

Numbers and names are fictional: 555-01xx numbers in area code 201 (libphonenumber accepts them) and the contact "E2E Test Contact". The seeded SMS threads are deleted and written again when they differ.

## Files

| File | Role |
|------|------|
| `e2e.py` | The command: arguments, the emulator, the scenarios in order |
| `fake_mac.py` | The fake Mac: identity, capability, pairing and sessions |
| `mac_crypto.py` | Keys, PIN pairing, session keys, envelopes, chunks (from `tools/vectors`) |
| `mac_pairing.py`, `mac_session.py` | `/v1/pair` with a PIN; `/v1/ctl` with acks, events and schema checks |
| `transport.py` | TLS 1.3 with the certificate pin, WebSocket with ping every 15 s |
| `pair_store.py`, `schema_check.py`, `bench_lines.py` | The pair file, the schema checks, the `HLBENCH/1` lines |
| `adb_device.py`, `ui_automator.py` | adb, the emulator console, the providers; the screen read by `uiautomator` with texts from the string catalog |
| `relay_client.py` | The client on the relay stack: registration, JWT, pairs, APNs token, `/v1/relay`, a relay channel for the session |
| `scenario_*.py`, `steps.py` | The scenarios (`scenario_common.py`: permissions and fictional numbers) and their PASS/FAIL lines |
| `self_test.py`, `fake_phone.py` | The self-test (CI): the crypto against the vectors, the whole client against an in-process fake phone, then the same session through the fake relay of `tools/bench` |

```sh
tools/.venv/bin/python tools/e2e/self_test.py      # must print "0 failed"
```
