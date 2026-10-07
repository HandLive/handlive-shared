# Changelog

All notable changes to this repository are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Call bench: app call rows in `tools/bench/call_latency.py` (CALL-05): delivery over the LAN and the relay, the
  Mac panel, decline, end and direct answer on the phone, tap-to-answer counted, and the tap back on the Mac.

### Fixed

- Call bench: the app call events are no longer skipped as unknown, and a tap on an app call no longer shows up as
  a cellular action with `phone=?`.

## [2026-09-30]

### Added

- Mac Settings permission strings: Check Again, Local Network unknown state, and the permissions footer
  (`settings.check_again`, `settings.local_network_unknown`, `settings.permissions_footer_mac`).
