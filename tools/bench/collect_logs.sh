#!/usr/bin/env bash
# Record the HLBENCH/1 lines of one test session: the Android phone over adb and this Mac through `log stream`.
# Usage: tools/bench/collect_logs.sh [out_dir] [adb_serial]      (stop with Ctrl-C)
# Then:  python3 tools/bench/clip_latency.py <out_dir>/*.log
#        python3 tools/bench/reconnect_time.py <out_dir>/*.log
# The apps emit these lines only in debug builds with bench logging on (tools/bench/README.md).
set -euo pipefail

out="${1:-bench-logs/$(date +%Y%m%d-%H%M%S)}"
serial="${2:-}"
adb_args=()
if [ -n "$serial" ]; then adb_args=(-s "$serial"); fi
mkdir -p "$out"

command -v adb >/dev/null || { echo "adb not found (Android platform-tools)" >&2; exit 1; }
adb ${adb_args[@]+"${adb_args[@]}"} logcat -c
adb ${adb_args[@]+"${adb_args[@]}"} logcat -v raw -s HLBENCH:I > "$out/android.log" &
android_pid=$!
log stream --style compact --level info \
  --predicate 'subsystem == "app.handlive.mac" AND category == "bench"' > "$out/mac.log" &
mac_pid=$!

stop() {
  kill "$android_pid" "$mac_pid" 2>/dev/null || true
  wait 2>/dev/null || true
  echo
  echo "Logs: $out ($(grep -c 'HLBENCH/1 ' "$out/android.log" || true) Android lines, $(grep -c 'HLBENCH/1 ' "$out/mac.log" || true) Mac lines)"
  echo "Next: python3 tools/bench/clip_latency.py $out/*.log && python3 tools/bench/reconnect_time.py $out/*.log"
}
trap stop INT TERM
echo "Recording to $out. Run the scenarios of tools/bench/README.md, then press Ctrl-C."
wait
