English | [Tiếng Việt](README.vi.md)

# JSON Schema checks

Run from the root of `shared/` (handlive-shared). Examples are read from `docs/detailed-design/` of the hub repository — by default the parent directory of `shared/` in the workspace, overridden with `HANDLIVE_DOCS_DIR`.

```sh
tools/.venv/bin/python -m pip install -r tools/schemas/requirements.txt   # if the venv lacks it
tools/.venv/bin/python tools/schemas/check_schemas.py
```

Exits 0 when green (it prints `XANH`). Steps:

1. Every `shared/schemas/*.schema.json` is valid against the draft 2020-12 metaschema, its `$id` matches the file name and every `$ref` resolves; the error code enum matches table 0.8.1, the WebSocket close code enum matches table 0.8.3 and the `type` enum matches table 0.7.1 (read straight from `00-common-specs.md`).
2. Examples in `docs/detailed-design/`:
   - `00-common-specs.md`: **every** ```json block must be classified and pass its schema; `{op, data}` outside the session/capability sections is checked with `payload.schema.json`.
   - `01`–`08`: every envelope (`v` + `type`), every ack (`re` + `ok`) and every `{op, data}` under a `WS session/<op>` or `WS capability/<op>` heading is checked. A `session` envelope whose payload decodes from base64 to JSON also has its handshake plaintext checked. Other objects (clipboard or sms ops, REST, push) are out of scope and only counted.
   - A ```json block that does not parse as a whole is parsed line by line; a line that does not parse is a documentation error. Inline code counts only when it is valid JSON.
3. Hand-written positive samples (`sample_messages.py`) must pass; negative samples (each breaks exactly one thing: a missing field, a wrong `v`, an unknown `type`, an unknown error code, a malformed uuid, bad b64…) must be rejected.
4. The UI string catalog excerpt quoted in 0.12.1 (the ```jsonc block with `strings`) passes `strings/ui-strings.schema.json` and the rules of `tools/strings/catalog_rules.py`, except the key order.

## Placeholder substitution

A placeholder is a string like `"<...>"` (for example `"<b64>"`, `"<request id>"`), a string containing `…` (for example `"…"`, `"0192f4a0-…"`), or exactly `"..."`. It is replaced according to the **name of the key** that holds it, and each substitution is printed:

| Key | Replacement |
|-----|-------------|
| `id`, `re` | `01920000-0000-7000-8000-000000000000` (UUIDv7) |
| `pair_id` | `00000000-0000-4000-8000-000000000000` (UUIDv4) |
| `device_id` | `00000000-0000-8000-8000-000000000000` (UUIDv8) |
| `payload` | Base64 with padding of 40 zero bytes (nonce 24 + tag 16) |
| `eph`, `nonce`, `mac` | b64u without padding of 32 zero bytes |

A placeholder under any other key is an error, never skipped.

## Known spec issues

`KNOWN_SPEC_ISSUES` in `doc_examples.py` lists documentation examples that contradict the spec itself, with the reason (this tool never edits `docs/`). Such an entry must keep failing; once the documentation is fixed and the example passes, the script reports it so the entry is removed.
