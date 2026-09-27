English | [Tiếng Việt](README.vi.md)

# Local relay stack

The HandLive cloud relay and everything it needs, on one development machine, for end-to-end tests of the real apps: the phone on an Android emulator reaches the relay as it would reach `relay.example.com`, and every push the relay sends to Apple or Google lands in a capture file instead.

| Part | Where | Notes |
|------|-------|-------|
| PostgreSQL | `127.0.0.1:55433` | Homebrew PostgreSQL 18 (`HANDLIVE_PG_BIN`), a temporary cluster in the state directory, Unix sockets off, dev credentials of `relay/.env.example` |
| Redis | `127.0.0.1:56380` | No persistence (`HANDLIVE_REDIS_SERVER`) |
| Relay | `http://127.0.0.1:18080` | `relay/target/debug/relay-server` (built with cargo when missing or with `--build`); migrations run at start; a fresh `RELAY_JWT_SECRET` per start, kept only in its environment; `RELAY_TRUSTED_PROXIES=127.0.0.1` |
| TLS front | `https://127.0.0.1:18443`, from the emulator `https://10.0.2.2:18443` | `tls_front.py`: a test CA and a server certificate for 10.0.2.2, 127.0.0.1 and localhost; appends `X-Forwarded-For`, like the reverse proxy of a deployment |
| Mock APNs | `http://127.0.0.1:18444`, sandbox under `/sandbox` | `mock_apns.py`: HTTP/2 with prior knowledge, as the relay's client speaks to a local URL; checks the ES256 provider token |
| Mock FCM | `http://127.0.0.1:18445` | `mock_fcm.py`: `messages:send` and the OAuth token endpoint the service-account JSON names; checks the RS256 assertion and the access token |

Ports are fixed per state directory by its first `up`, because the Android build bakes the TLS front's port into the APK. The state directory (`--state-dir`, else `$HANDLIVE_RELAY_STACK_DIR`, else `$TMPDIR/handlive-relay-stack`) holds the generated keys, the data, the logs, the captures and `relay_stack.json`; it is never inside a repository. Keys and certificates are generated there, used only with the local mocks and front, and never committed.

## Use

```sh
tools/.venv/bin/python -m pip install -r tools/e2e/relay_stack/requirements.txt
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py up          # prints the endpoints, the pin, the captures
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py check       # health forward push: every line PASS or FAIL
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py check android --wait-s 60
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py captures --provider apns --prk <hex PRK of the pair>
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py status      # exit 1 when a process is down
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py down        # --wipe also deletes data, logs, captures
tools/.venv/bin/python tools/e2e/relay_stack/self_test.py               # the parts without services (CI)
```

`up` writes everything a client needs to `<state-dir>/relay_stack.json`: the relay URLs (plain, TLS, WebSocket, from the emulator), the CA file and the environment for Python clients (`SSL_CERT_FILE`), the SPKI pin and the Gradle arguments of the Android build, the APNs topic, key id and team id, the mock URLs and capture files, the PostgreSQL URL and the log files.

| Check | What passes |
|-------|-------------|
| `health` | The relay listens after applying its migrations; `_sqlx_migrations` has every file of `relay/migrations`; Redis answers; the relay answers through the TLS front (certificate verified against the CA); the mocks listen |
| `forward` | `tools/bench/relay_load.py` through the TLS front: fake devices register (HLREG1), authenticate (HLAUTH1), pair, open `/v1/relay`; every text wrapper and binary `HR` frame reaches the peer (CONN-03 API 6) |
| `push` | Fake devices send `POST /v1/push`: `call_incoming`, `sms_new`, `call_missed` reach the mock APNs as CONN-04 API 4 says (headers, `loc-key`, `thread-id`, `interruption-level`, `apns-collapse-id`, `apns-expiration`, `hl` byte for byte, opened with the pair's `K_push`); a wake reaches the mock FCM as API 3 says and a second one is coalesced; a dead token gives 409 and is deleted (E3) |
| `android` | The real app's row in `devices`, and in the TLS front's log with the OkHttp User-Agent: `POST /v1/devices`, the challenge and token (JWT), `GET /v1/relay 101`; its presence in Redis; its pairs |

Logs never hold payloads: the relay logs path, status, size and time; the front logs client address, method, path without the query, status, TLS version and User-Agent; the captures hold what the providers would receive minus credentials. The checks print only the envelope type and op of a decrypted `hl`, never numbers or text.

## The Android app

```sh
tools/e2e/relay_stack/build_android_for_local_relay.sh --serial emulator-5554 \
    --patch pins-without-port --patch debug-trust
```

The script exports the committed `android/` tree next to links to `../shared` and `../docs`, builds `:app:assembleFossDebug` with `-Phandlive.relayHost=10.0.2.2:18443 -Phandlive.relayExtraPins=<pin>` on the command line only, and installs the APK with `adb install -r` (the app keeps its data; its service restarts on `MY_PACKAGE_REPLACED`). `android/` and its build outputs are never touched.

Without the two patches the current app cannot use this stack:

- **pins-without-port** — `OkHttpRelayTransport` adds the pins for `RELAY_HOST` as is. A host with a port is no `CertificatePinner` pattern: `IllegalArgumentException: Invalid pattern: 10.0.2.2:18443`. Every relay task swallows it, so nothing reaches the relay, and opening Settings crashes the app (the relay status flow). A local relay rarely gets port 443 (macOS lets a user bind it only on all interfaces, and something often holds it), so the port is needed. The patch pins the URL's host name.
- **debug-trust** — the app trusts only the system CAs, before any pin: the TLS front logs `TLS handshake failed: SSLV3_ALERT_CERTIFICATE_UNKNOWN`. The patch adds a debug-only network security config (`debug-overrides`) that also trusts the stack's CA, copied into the export as `res/raw/local_relay_ca.pem`; OkHttp still checks the pin.

The app registers its device when its service starts with the relay on. It asks for a token (challenge → HLAUTH1 → JWT) only when it has something to do there: registering a new pair, a push. It joins `/v1/relay` on a demand of CONN-03 step 2: the service starts with a relay-registered pair and no session, a LAN session ends without `session/bye`, an SMS or a ringing call for a client without a session, a pairing rendezvous.

## With the fake client of `tools/e2e/`

1. `relay_stack.py up`, then build and install the app with both patches (above).
2. Register the fake client with the relay before pairing: `stack_rest.FakeDevice(platform, seed)` with the client's Ed25519 seed, `register(...)` (HLREG1, then HLAUTH1). The phone registers the pair right after pairing; if the client is not registered yet it gets 404 and waits 24 h (PAIR-01 API 8 logic 6).
3. Pair by PIN over the LAN (`adb forward`). The app then calls `/v1/auth/challenge`, `/v1/auth/token` and `POST /v1/pairs` (201).
4. Relay path: drop the LAN session without `session/bye`; the app opens `/v1/relay`. Open `wss://127.0.0.1:18443/v1/relay` with the client's JWT (CA in `SSL_CERT_FILE`), read `presence`, and run the `/v1/ctl` session with `{"to", "env"}` wrappers (0.4.3).
5. Push path: pair a fake iPhone (`platform ios`), put its token with `PUT /v1/devices/me/push-token` (`provider` `apns_sandbox`, `topic` `app.handlive.ios`, the token in hex; one that starts with `dead` gets 410). With the iPhone off its session, send an SMS or ring the emulator (`adb emu sms send`, `adb emu gsm call`, fake numbers only): the app sends `POST /v1/push`, and `captures --provider apns --prk <PRK>` shows it with the decrypted envelope type and op.
6. `check android` sums up what the app did.

After `down` and `up` the relay has a new JWT secret. The current app keeps its token and gets `401 SIGNATURE_INVALID` on `/v1/relay` until the token expires (up to 15 minutes); restart the app (install the APK again) after restarting the stack.

## What it cannot prove

- Delivery by Apple and Google: real tokens, APNs and FCM acceptance, the notification on a device. The mocks check what the relay sends, not what the providers do with it.
- The production TLS path: a Let's Encrypt certificate on a VPS and the ISRG Root X1/X2 pins. The app is tested with a patched debug build; the release build keeps the system trust.
- FCM wake-ups of the real app: the `foss` flavor has no Firebase and registers no push token; wakes are checked with fake devices only.
- Several relay instances, a real reverse proxy, mobile networks and NAT timeouts.

## Files

| File | Purpose |
|------|---------|
| `relay_stack.py` | `up`, `down`, `status`, `check`, `captures` |
| `stack_config.py`, `stack_processes.py` | Ports, state layout, `relay_stack.json`; processes, PostgreSQL, Redis |
| `local_keys.py` | Test CA and server certificate, SPKI pins, APNs key, FCM service account |
| `tls_front.py` | TLS front with `X-Forwarded-For` |
| `mock_apns.py`, `mock_fcm.py`, `jwt_verify.py`, `capture_log.py` | Mock providers, token checks, capture files |
| `stack_rest.py`, `push_crypto.py` | Fake devices (HLREG1, HLAUTH1, pairs); push envelopes sealed and opened with `K_push` |
| `stack_checks.py`, `push_checks.py`, `check_report.py` | The checks |
| `build_android_for_local_relay.sh`, `android_patches/` | Android build for the stack; the two proposed debug-only patches |
| `self_test.py` | Parts without services (CI) |
| `requirements.txt` | Pinned: the load test's requirements plus `h2`, `hpack`, `hyperframe` (MIT) |
