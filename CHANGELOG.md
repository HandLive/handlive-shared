# Changelog

All notable changes to this repository are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
