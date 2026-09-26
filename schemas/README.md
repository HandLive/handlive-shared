English | [Tiếng Việt](README.vi.md)

# HandLive protocol JSON Schemas

JSON Schema draft 2020-12 for the device ↔ device messages, the relay's WebSocket frames and REST bodies, and the push bodies, derived from `docs/detailed-design/00-common-specs.md` (0.3, 0.4.3, 0.4.4, 0.5.1, 0.6.3, 0.7.1–0.7.4, 0.8.1–0.8.3) and the detailed specs PAIR-01…03, CONN-01…04, CLIP-01…04 and SMS-01…05. Android (`core/protocol`), Apple (`HLProtocol`) and the relay use them as the reference in their tests.

`$id` = `https://handlive.app/schemas/v1/<file>`: only an identifier, never fetched over the network. `$ref`s between files use relative paths (`common.schema.json#/$defs/uuid-v7`), so load the whole directory into the validator library's registry.

| File | Object | Source |
|------|--------|--------|
| `common.schema.json` | `$defs` only: `uuid`, `uuid-v4` (`pair_id`), `uuid-v7` (`id`, `re`), `uuid-v8` (`device_id`), `int32`, `int64`, `timestamp`, `b64`, `b64u`, `b64u-16` (`rv_id`), `b64u-32`, `b64u-64` (Ed25519 signatures), `ws-close-code` (WebSocket close codes), `platform` | 0.2, 0.3, 0.8.3 |
| `envelope.schema.json` | Envelope `{v, type, id, ts, payload}`; `$defs/type` = the `type` enum | 0.5.1, 0.7.1 |
| `payload.schema.json` | Generic plaintext `{op, data}` | 0.5.1 |
| `ack.schema.json` | Ack plaintext; `$defs/success`, `$defs/failure` | 0.5.1 |
| `error.schema.json` | `ack.error` `{code, message, details?}`; `$defs/code` = the error code enum | 0.8.1 |
| `session-hello.schema.json` | `session/hello` | 0.6.3; CONN-01 API 4 |
| `session-welcome.schema.json` | `session/welcome` | 0.6.3; CONN-01 API 5 |
| `session-error.schema.json` | `session/error` | 0.6.3; CONN-01 API 6 |
| `session-rekey.schema.json` | `session/rekey`; `$defs/ack` = the success ack carrying `{epoch, eph, nonce}` | 0.6.3; CONN-02 API 3 |
| `session-bye.schema.json` | `session/bye` | 0.7.1; PAIR-03 API 2 |
| `capability-hello.schema.json` | `capability/hello`; `$defs/capability-data` shared | 0.7.2 |
| `capability-update.schema.json` | `capability/update` (same `data` as hello) | 0.7.2 |
| `pair-hello`, `pair-offer`, `pair-confirm`, `pair-done`, `pair-error` `.schema.json` | The pairing handshake (unencrypted payloads) | 0.6.2; PAIR-01 API 2–6 |
| `pair-revoke.schema.json` | `pair/revoke`; `$defs/ack` = the success ack with empty `data` | PAIR-03 API 1 |
| `ping-ping.schema.json` | `ping/ping` through the relay; `$defs/ack` = `{seq, server_ts}` | CONN-02 API 2 |
| `clipboard-push.schema.json` | `clipboard/push` (inline text or `transfer`); `$defs/ack` = `{clip_id, status, reason?}` | CLIP-01 API 5, CLIP-03 API 3, CLIP-04 API 4 |
| `clipboard-conflict.schema.json`, `clipboard-cancel.schema.json` | `clipboard/conflict`, `clipboard/cancel` | CLIP-01 API 6, CLIP-03 API 5 |
| `sms-common.schema.json` | `$defs` only: the `thread` and `message` objects, `synced-message` (no `local_id`), `unread-entry`, `message-key`, `thread-id`, `address`, `sub-id` | SMS-01 API 1 |
| `sms-sync.schema.json`, `sms-history.schema.json` | `sms/sync`, `sms/history`; `$defs/ack` = the page they return | SMS-01 API 1, SMS-03 API 1 |
| `sms-new.schema.json`, `sms-status.schema.json`, `sms-read_changed.schema.json` | `sms/new` (also the push envelope), `sms/status`, `sms/read_changed` | SMS-02 API 1, SMS-04 API 2, SMS-05 API 1 |
| `sms-send.schema.json` | `sms/send`; `$defs/ack` = `{accepted, parts}` | SMS-04 API 1 |
| `sms-notification.schema.json` | The new SMS notification content on Mac/iOS (identifiers and `userInfo`) — local, not a wire message | SMS-02 API 4 |
| `relay-wrapper.schema.json` | Routing wrapper on `/v1/relay`: `$defs/outbound` `{to, env}`, `$defs/inbound` `{from, env}` | 0.4.3; CONN-03 API 6 |
| `relay-presence`, `relay-error`, `relay-rv_join`, `relay-rv_joined`, `relay-rv_msg`, `relay-pair_revoked` `.schema.json` | Relay control messages `{op, …}` (not E2E, no `data`) | 0.7.3; CONN-03 API 5, PAIR-01 API 7, PAIR-03 API 4 |
| `relay-rest.schema.json` | `$defs` only: every relay REST request and response body (`devices-request` … `push-response`), `error-response` and `error-code` | 0.7.4, 0.8.2 |
| `push.schema.json` | `$defs` only: `fcm-data`, `fcm-request`, `fcm-response`, `apns-payload` | 0.4.4; CONN-04 API 3–4 |

The UI string catalog has its own schema next to it: `../strings/ui-strings.schema.json`.

## Usage

1. Validate the envelope with `envelope.schema.json`.
2. Decrypt `payload` (handshake messages `session` hello/welcome/error: only decode the base64).
3. `type = ack` → `ack.schema.json` (or `<op>#/$defs/ack` when the op has its own ack data, for example `session-rekey`, `sms-sync`); any other `type` → `<type>-<op>.schema.json` when it exists, else `payload.schema.json`.

On `/v1/relay`: a text frame with `op` is a relay control message → `relay-<op>.schema.json`; a text frame with `to`/`from` is the routing wrapper → `relay-wrapper.schema.json` (its `env` is an envelope, handled as above). REST bodies and push bodies are `$defs` of `relay-rest.schema.json` and `push.schema.json` (`relay-rest.schema.json#/$defs/push-request`). Binary `HR` frames are not JSON: see `../test-vectors/relay-frame.json`.

## Strict conventions

The schemas check **messages a sender emits** (each platform's tests validate the messages it produces). A receiver does not use them to reject input: by 00-common-specs 0.5.1 rule 6, unknown fields are ignored and unknown enum values do not break a message.

- `v` = 1; `type` is one of the 10 values of 0.7.1; `id` and `re` are lowercase 36-character UUIDv7s (version nibble `7`, variant `8|9|a|b`); `device_id` is a UUIDv8, `pair_id` a UUIDv4.
- `ts` is an int64 ≥ 0; `payload` is standard Base64 with padding; `eph`, `nonce`, `mac` are b64u of exactly 32 bytes (43 characters, canonical form).
- `additionalProperties: false` on every object whose fields the spec lists in full, including each feature in `features`.
- Capability: only `enabled` is required in each feature; fields marked "Android/Mac/iOS only" are optional. `bt_address` looks like `A1:B2:C3:D4:E5:F6` (uppercase, colons, as in the AUDIO-01 example) or is `null`.
- `session/error`: `code` ∈ {`AUTH_FAILED`, `PAIR_UNKNOWN`, `PAIR_REVOKED`, `UNSUPPORTED_VERSION`, `RATE_LIMITED`}; `min_protocol` is required if and only if `code = UNSUPPORTED_VERSION`.
- WebSocket close codes (`common.schema.json#/$defs/ws-close-code`) follow the table of 0.8.3, including 4410 `REKEY_FAILED`, 4411 `IDLE_TIMEOUT` and 4429 `RATE_LIMITED`; `check_schemas.py` compares them with the table.
- SMS: a message in an `sms/sync` or `sms/history` ack never carries `local_id`; the sync ack carries `page_token` if and only if `has_more = true` and `unread` (entries with `unread_count ≥ 1`) only on the last page; `sms/send` has exactly one recipient and a body of 1–1,600 characters that is not only whitespace; `sms/status` carries `error_code` (one of the four sending errors) if and only if `status = failed`; the SMS notification uses the category `HL_SMS`, or `HL_SMS_GROUP` for a conversation with several addresses, and for a push I-NSE sets `threadIdentifier` after decrypting.
- Clipboard: exactly one of `text` and `transfer`; images need `transfer`, `width`, `height` and an image MIME type; `chunk_size` = 65,536; an `ignored` ack carries `reason`.
- Relay: `rv_id` is b64u of exactly 16 bytes (22 characters); `rv_msg` carries only `pair` envelopes; the relay `error` op uses `NOT_PAIRED`, `NOT_CONNECTED`, `PAYLOAD_TOO_LARGE`, `RATE_LIMITED`, `BAD_REQUEST`, and `BAD_REQUEST` never carries `to` (a malformed id is never echoed); REST error bodies use the 0.8.2 codes (compared with the table), without `details`; signatures are b64u of exactly 64 bytes; the attestation is b64u of the 127 bytes starting with `HLPAIR1`; `expires_in` = 900.
- Push: `kind = wake` goes with `user_open`, `sms_send`, `call_action` and no `env_b64`; `kind = alert` with `sms_new`, `call_incoming`, `call_missed` and `env_b64` (≤ 3,000 characters, b64 of the JSON envelope encrypted with `K_push`); FCM carries only `{t, p, r}`; the APNs alert has only a `loc-key` of the `push` group of the UI string catalog (compared with CONN-04 API 4 and the catalog), `time-sensitive` only for `push.call_incoming`; the APNs `thread-id` is the generic `sms` or `calls`; `collapse_key` is printable ASCII of 1–64 characters: the `message_key` for `sms_new` (`sms:12847`), `call:<call_id>` for `call_incoming`, `call:<call_id>` or `calllog:<entry_id>` for `call_missed`; `ttl_s` is 0–86,400, and the phone sends 86,400 with `sms_new` and `call_missed`, 30 with `call_incoming`; FCM `android.ttl` is at most `"60s"` and `android.collapse_key` is always `wake`.

To add an op or an error code: change `00-common-specs.md` first, then the schema, then run `tools/.venv/bin/python tools/schemas/check_schemas.py` (see `tools/schemas/README.md`).
