English | [Tiếng Việt](README.vi.md)

# HandLive protocol JSON Schemas

JSON Schema draft 2020-12 for the device ↔ device messages, derived from `docs/detailed-design/00-common-specs.md` (0.3, 0.5.1, 0.6.3, 0.7.1, 0.7.2, 0.8.1, 0.8.3) and the detailed specs CONN-01/CONN-02/PAIR-03. Android (`core/protocol`), Apple (`HLProtocol`) and the relay use them as the reference in their tests.

`$id` = `https://handlive.app/schemas/v1/<file>`: only an identifier, never fetched over the network. `$ref`s between files use relative paths (`common.schema.json#/$defs/uuid-v7`), so load the whole directory into the validator library's registry.

| File | Object | Source |
|------|--------|--------|
| `common.schema.json` | `$defs` only: `uuid`, `uuid-v4` (`pair_id`), `uuid-v7` (`id`, `re`), `uuid-v8` (`device_id`), `int32`, `int64`, `timestamp`, `b64`, `b64u`, `b64u-32`, `ws-close-code` (WebSocket close codes) | 0.2, 0.3, 0.8.3 |
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

The UI string catalog has its own schema next to it: `../strings/ui-strings.schema.json`.

## Usage

1. Validate the envelope with `envelope.schema.json`.
2. Decrypt `payload` (handshake messages `session` hello/welcome/error: only decode the base64).
3. `type = ack` → `ack.schema.json` (or `<op>#/$defs/ack` when the op has its own ack, for example `session-rekey`); any other `type` → `<type>-<op>.schema.json` when it exists, else `payload.schema.json`.

## Strict conventions

The schemas check **messages a sender emits** (each platform's tests validate the messages it produces). A receiver does not use them to reject input: by 00-common-specs 0.5.1 rule 6, unknown fields are ignored and unknown enum values do not break a message.

- `v` = 1; `type` is one of the 10 values of 0.7.1; `id` and `re` are lowercase 36-character UUIDv7s (version nibble `7`, variant `8|9|a|b`); `device_id` is a UUIDv8, `pair_id` a UUIDv4.
- `ts` is an int64 ≥ 0; `payload` is standard Base64 with padding; `eph`, `nonce`, `mac` are b64u of exactly 32 bytes (43 characters, canonical form).
- `additionalProperties: false` on every object whose fields the spec lists in full, including each feature in `features`.
- Capability: only `enabled` is required in each feature; fields marked "Android/Mac/iOS only" are optional. `bt_address` looks like `A1:B2:C3:D4:E5:F6` (uppercase, colons, as in the AUDIO-01 example) or is `null`.
- `session/error`: `code` ∈ {`AUTH_FAILED`, `PAIR_UNKNOWN`, `PAIR_REVOKED`, `UNSUPPORTED_VERSION`, `RATE_LIMITED`}; `min_protocol` is required if and only if `code = UNSUPPORTED_VERSION`.
- WebSocket close codes (`common.schema.json#/$defs/ws-close-code`) follow the table of 0.8.3, including 4410 `REKEY_FAILED`, 4411 `IDLE_TIMEOUT` and 4429 `RATE_LIMITED`; `check_schemas.py` compares them with the table.

To add an op or an error code: change `00-common-specs.md` first, then the schema, then run `tools/.venv/bin/python tools/schemas/check_schemas.py` (see `tools/schemas/README.md`).
