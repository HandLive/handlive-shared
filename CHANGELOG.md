# Changelog

All notable changes to this repository are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.0] — 2026-10-30

### Added

- **Phase 7 (offline connectivity):** test vectors for the Bluetooth L2CAP link-security handshake (Noise prologue,
  challenge, `noise1`, `noise2`, `bt-link.json`), the pre-auth/transport frame codec (channel IDs, record length bounds,
  `bt-frame.json`), advertisement service data (rotating hint, `bt-advertisement.json`) and CPace-X25519-SHA512
  password-authenticated key exchange (`cpace.json`, draft vectors plus HandLive-specific cases); Bluetooth pairing
  envelopes (`bt-pairing.json`) — all consumed by `core/crypto`/`core/protocol`/`core/transport` on Android and
  `HLCrypto`/`HLProtocol`/`HLTransport` on Apple; `tools/setup-cpace-refs.sh` fetches the CPace draft and verifies the
  vectors in per-tool venvs. `envelope.schema.json`/`error.schema.json`: new envelope types `direct` and `bulk` (both
  already in the Android/Apple `MessageType` enum).

- UI strings for the device label "Connected via Bluetooth" (`status.connected_bluetooth(_to)`, CONN-05, shown by the
  status indicator on Android/Mac/iOS) and the Mac Bluetooth permission prompt text (`infoplist.bluetooth_always`, wired
  into `macOS/Info.plist`'s `NSBluetoothAlwaysUsageDescription`).

### Specs

- Catalog entries added for 01-setup-settings.md SET-01/SET-03 that no Android/Apple UI calls yet: the Bluetooth
  permission-primer screen (`permission.bluetooth_title/body/body_mac`), the Mac "Bluetooth off"/"Bluetooth denied"
  status lines and their settings button (`status.bluetooth_off`, `status.bluetooth_denied`,
  `common.open_bluetooth_settings`), and the Settings feature-card label (`settings.bluetooth_link`).
- `error.schema.json`'s new `DIRECT_WIFI_UNAVAILABLE` code (0.4.6): schema only, no code returns or handles it yet —
  Wi-Fi Direct itself (SSID/passphrase format, per-connection bulk stream keys `K_bulk`) has no code or test vectors on
  either platform.
- `bt_seen`/`bt_lost`/`wifi_assoc` bench events (`tools/bench/reconnect_time.py`): the trigger logic is in place, but
  only `tools/ble-spike` and `Tools/BLESpike` emit these events today — the shipped app does not yet.

## [0.1.1] — 2026-10-22

### Changed

- `tools/e2e`: the adb device helper, the fake Mac and the scenario namespaces follow the new Android application id
  `com.handlive.android`; no change to the test vectors, schemas or design tokens, so the contract of
  `v0.1.0-beta.3` stands. This tag only pairs the workspace with the `v0.1.1` platform releases.

## [0.1.0-beta.3] — 2026-10-07

### Added

- Clipboard HTML: `clipboard/push` takes an optional `html` next to an inline text (schema and README), and
  `test-vectors/clipboard-html.json` defines the HTML sanitizer every platform runs on it, with its reference
  builder and a checker that re-runs every case; the fake Mac lists `text/html` among its clipboard types, and the
  e2e clipboard steps cover HTML applied, sent back sanitized, and refused with a transfer or an image (#4).
- Strings for the Auto-Send on Copy action sheet shown while auto-send is not on yet (SET-02 field 39) (#5).
- Call bench: app call rows in `tools/bench/call_latency.py` (CALL-05): delivery over the LAN and the relay, the
  Mac panel, decline, end and direct answer on the phone, tap-to-answer counted, and the tap back on the Mac (#6).
- e2e: a scenario for calls of other apps (`app_calls`) driven by the debug-only fake calling app: label, decline,
  a swiped in-call notification, hang-up; the bench self-test covers a second Mac and a resent tap-to-answer (#7).
- e2e: phone to Mac image through Chrome's Copy image and the Send Clipboard button; the fake Mac takes chunked
  clipboard pushes from the phone (#1).
- Bench: the `clip_read_failed` event of a phone that could not read a clip, with its stage, MIME types and item
  parts (#1, #3).

### Fixed

- e2e: the battery-optimization exemption is granted when uiautomator cannot see Android 10's system dialog (#2).
- Call bench: the app call events are no longer skipped as unknown, a tap on an app call no longer shows up as a
  cellular action with `phone=?`, one change times one send per Mac, only the first intent of an action is timed,
  and a line whose clock field is not a number is skipped instead of stopping the run (#6).
- Clipboard HTML: the reference sanitizer finds tags in linear time (repeated `<a` with no `>` after it, or before
  an unclosed quote, took seconds per 10 KB); output unchanged; three vectors for these inputs in
  `clipboard-html.json`, and a check that about 1 MiB of each is sanitized within 5 s (#8).

## [2026-09-30]

### Added

- Mac Settings permission strings: Check Again, Local Network unknown state, and the permissions footer
  (`settings.check_again`, `settings.local_network_unknown`, `settings.permissions_footer_mac`).
