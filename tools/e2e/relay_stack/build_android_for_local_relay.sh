#!/usr/bin/env bash
# Build the Android app (foss debug) for the local relay stack and install it on an emulator.
#
#   tools/e2e/relay_stack/build_android_for_local_relay.sh --serial emulator-5554 [--state-dir DIR]
#       [--patch pins-without-port] [--patch debug-trust] [--no-install]
#
# Reads <state-dir>/relay_stack.json (written by relay_stack.py up): the relay host as the emulator sees it
# (10.0.2.2:<TLS front port>) and the SPKI pin of the stack's CA. Exports the committed android/ tree (git archive
# HEAD) into <state-dir>/android-build/ws/android next to links to ../shared and ../docs, so android/ and its build
# outputs are never touched, then builds :app:assembleFossDebug with -Phandlive.relayHost and
# -Phandlive.relayExtraPins on the command line only. The APK is copied to <state-dir>/android-build/ and installed
# with `adb -s <serial> install -r` (the app keeps its data; its service restarts on MY_PACKAGE_REPLACED).
#
# --patch applies a proposed debug-only change from android_patches/ to the exported copy (never to android/):
#   pins-without-port  OkHttpRelayTransport keys the pins by the URL's host: today a relay host with a port makes
#                      CertificatePinner.Builder.add throw IllegalArgumentException("Invalid pattern").
#   debug-trust        a debug-only network security config that trusts the stack's CA (res/raw/local_relay_ca.pem,
#                      copied from the state directory into the export only).
# Without both, the app cannot reach a relay on a port other than 443 with a self-signed certificate (README.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$HERE/../../../.." && pwd)"
STATE_DIR="${HANDLIVE_RELAY_STACK_DIR:-${TMPDIR:-/tmp}/handlive-relay-stack}"
SERIAL=""
INSTALL=1
PATCHES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --serial) SERIAL="$2"; shift 2 ;;
    --patch) PATCHES+=("$2"); shift 2 ;;
    --no-install) INSTALL=0; shift ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

STACK_JSON="$STATE_DIR/relay_stack.json"
[ -f "$STACK_JSON" ] || { echo "no $STACK_JSON: run relay_stack.py up first" >&2; exit 1; }
if [ "$INSTALL" = 1 ] && [ -z "$SERIAL" ]; then
  echo "pass --serial <adb serial> (or --no-install)" >&2
  exit 2
fi

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
read_json() {  # read_json key [key …]: one value of relay_stack.json
  python3 - "$STACK_JSON" "$@" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
for key in sys.argv[2:]:
    value = value[key]
print(value)
PY
}
RELAY_HOST="$(read_json android_build relay_host)"
EXTRA_PINS="$(read_json android_build relay_extra_pins)"
CA_CERT="$(read_json tls ca_cert)"

BUILD_DIR="$STATE_DIR/android-build"
WS="$BUILD_DIR/ws"
COMMIT="$(git -C "$WORKSPACE/android" rev-parse --short HEAD)"
echo "android $COMMIT → $WS/android (relay host $RELAY_HOST, extra pin $EXTRA_PINS, patches: ${PATCHES[*]:-none})"
rm -rf "$WS/android"
mkdir -p "$WS/android"
git -C "$WORKSPACE/android" archive HEAD | tar -x -C "$WS/android"
ln -sfn "$WORKSPACE/shared" "$WS/shared"
ln -sfn "$WORKSPACE/docs" "$WS/docs"
[ -f "$WORKSPACE/android/local.properties" ] && cp "$WORKSPACE/android/local.properties" "$WS/android/"

for patch in "${PATCHES[@]+"${PATCHES[@]}"}"; do
  case "$patch" in
    pins-without-port) file="$HERE/android_patches/relay-pins-without-port.patch" ;;
    debug-trust)
      file="$HERE/android_patches/debug-trust-local-relay-ca.patch"
      mkdir -p "$WS/android/app/src/debug/res/raw"
      cp "$CA_CERT" "$WS/android/app/src/debug/res/raw/local_relay_ca.pem" ;;
    *) echo "unknown patch: $patch (pins-without-port, debug-trust)" >&2; exit 2 ;;
  esac
  (cd "$WS/android" && git apply --verbose "$file")
done

LOG="$BUILD_DIR/gradle.log"
echo "building :app:assembleFossDebug (log $LOG) …"
if ! (cd "$WS/android" && perl -e 'alarm shift; exec @ARGV' 1800 ./gradlew --console=plain -q :app:assembleFossDebug \
      "-Phandlive.relayHost=$RELAY_HOST" "-Phandlive.relayExtraPins=$EXTRA_PINS") >"$LOG" 2>&1; then
  tail -40 "$LOG" >&2
  echo "build failed; full log: $LOG" >&2
  exit 1
fi
SUFFIX="$(IFS=+; echo "${PATCHES[*]:-unpatched}")"
APK="$BUILD_DIR/app-foss-debug-local-relay-$SUFFIX.apk"
cp "$WS/android/app/build/outputs/apk/foss/debug/app-foss-debug.apk" "$APK"
echo "APK: $APK"

if [ "$INSTALL" = 1 ]; then
  ADB="${ADB:-$(command -v adb || echo /opt/homebrew/share/android-commandlinetools/platform-tools/adb)}"
  perl -e 'alarm shift; exec @ARGV' 300 "$ADB" -s "$SERIAL" install -r "$APK"
  echo "installed on $SERIAL; the service restarts by itself (MY_PACKAGE_REPLACED)"
fi
