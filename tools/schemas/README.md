English | [Tiếng Việt](README.vi.md)

# JSON Schema checks

Run from the root of `shared/` (handlive-shared). Examples are read from `docs/detailed-design/` of the hub repository — by default the parent directory of `shared/` in the workspace, overridden with `HANDLIVE_DOCS_DIR`.

```sh
tools/.venv/bin/python -m pip install -r tools/schemas/requirements.txt   # if the venv lacks it
tools/.venv/bin/python tools/schemas/check_schemas.py
```

Exits 0 when green (it prints `XANH`). Steps:

1. Every `shared/schemas/*.schema.json` is valid against the draft 2020-12 metaschema, its `$id` matches the file name and every `$ref` resolves; the error code enum matches table 0.8.1, the WebSocket close code enum matches table 0.8.3 and the `type` enum matches table 0.7.1 (read straight from `00-common-specs.md`). `relay_sms_spec_checks.py` adds: the `sms` ops and the ones that ack with data (0.7.1), the relay control ops (0.7.3, one `relay-<op>` file each), the relay REST endpoints and the `relay-rest` bodies of each (0.7.4), the relay error codes (0.8.2), the push `reason` enum (CONN-04 API 2) and the APNs `loc-key` enum (CONN-04 API 4), each of which must also be an iOS key of `strings/ui-strings.json`.
2. Examples in `docs/detailed-design/`:
   - `00-common-specs.md`: **every** ```json block must be classified and pass its schema; `{op, data}` outside the session/capability sections is checked with `payload.schema.json`.
   - `01`–`08` (both languages): every envelope (`v` + `type`), every ack (`re` + `ok`; the op's own ack under a `WS <type>/<op>` heading when it has one) and every `{op, data}` under a `WS <type>/<op>` heading for which a `<type>-<op>` schema exists (`session`, `capability`, `pair`, `ping`, `clipboard`, `sms`). A `session` envelope whose payload decodes from base64 to JSON also has its handshake plaintext checked. Relay frames are recognized by their shape (`{op, …}` without `data` → `relay-<op>`, `{to|from, env}` → `relay-wrapper`, `{error}` → `relay-rest#error-response`), REST and push bodies by the heading of their API section (`POST /v1/devices`, `FCM HTTP v1`, `APNs HTTP/2`…) and their fields, and the SMS notification content by its `HL_SMS` category. `env_b64` of `POST /v1/push` and `hl` of the APNs payload must decode to a valid envelope. Objects without a schema (camera, call and call audio ops of later phases) are only counted.
   - A ```json block that does not parse as a whole is parsed line by line; a line that does not parse is a documentation error. In a ```http block every line starting with `{` is a JSON body. Inline code counts only when it is valid JSON.
3. Hand-written positive samples (`sample_messages.py`, `sample_messages_sms.py`, `sample_messages_relay.py`) must pass; negative samples (each breaks exactly one thing: a missing field, a wrong `v`, an unknown `type`, an unknown error code, a malformed uuid, bad b64, a wake push with content…) must be rejected.
4. The UI string catalog excerpt quoted in 0.12.1 (the ```jsonc block with `strings`) passes `strings/ui-strings.schema.json` and the rules of `tools/strings/catalog_rules.py`, except the key order.
5. The wire messages inside `shared/test-vectors` pass their schemas: the `request` of `relay-auth.json`; the `pairs_request` and the `pair/*` plaintexts of `pair-handshake.json`; the `push_request`, `apns_payload` and `sms/new` plaintexts of `push-envelope.json` (with `env_b64`/`hl` decoded into an envelope); the text wrappers of `relay-frame.json`, whose malformed ones must also fail `relay-wrapper`.

## Placeholder substitution

A placeholder is a string like `"<...>"` (for example `"<b64>"`, `"<request id>"`), a string containing `…` (for example `"…"`, `"0192f4a0-…"`), or exactly `"..."`. It is replaced according to the **name of the key** that holds it, and each substitution is printed:

| Key | Replacement |
|-----|-------------|
| `id`, `re` | `01920000-0000-7000-8000-000000000000` (UUIDv7) |
| `pair_id` | `00000000-0000-4000-8000-000000000000` (UUIDv4) |
| `device_id` | `00000000-0000-8000-8000-000000000000` (UUIDv8) |
| `payload` | Base64 with padding of 40 zero bytes (nonce 24 + tag 16) |
| `eph`, `nonce`, `mac`, `prk_check` | b64u without padding of 32 zero bytes |
| `sig`, `sig_a`, `sig_b` | b64u without padding of 64 zero bytes |
| `attestation` | b64u of `HLPAIR1` followed by 120 zero bytes (127 bytes, 0.6.2) |
| `access_token` | A compact JWS (three b64u parts) |
| `token` | 64 hexadecimal zeros (an APNs token, also a valid FCM token string) |
| `env_b64`, `hl` | Base64 of a JSON envelope `{v, type: sms, id, ts, payload}` |
| `by` | `00000000-0000-8000-8000-000000000000` (UUIDv8) |
| `code`, `message` | `BAD_REQUEST` (a code of both 0.8.1 and 0.8.2), `diagnostic` |

A placeholder under any other key is an error, never skipped.

## Known spec issues

`KNOWN_SPEC_ISSUES` in `doc_examples.py` lists documentation examples that contradict the spec itself, with the reason (this tool never edits `docs/`). Such an entry must keep failing; once the documentation is fixed and the example passes, the script reports it so the entry is removed.
