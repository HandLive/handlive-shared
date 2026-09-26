English | [Tiếng Việt](README.vi.md)

# handlive-shared

This repository runs no app. It holds the test vectors, JSON Schemas, design tokens and UI string catalog that Android, Apple and the relay share. The other repositories read it through `../shared`.

Sources: `../docs/detailed-design/00-common-specs.md` and `../docs/design-system/` in the hub repository. The Python tools in `tools/` generate and check these files. See this repository's `CLAUDE.md`.

| Folder | Contents | Docs |
|--------|----------|------|
| `test-vectors/` | 20 vector files (RFC and generated, including `push-envelope.json` and `relay-frame.json`) plus the cross-platform `envelope-roundtrip{,-apple}.json` | `test-vectors/README.md` |
| `schemas/` | JSON Schema 2020-12: envelope, payload, ack, error, `session-*`, `capability-*`, `pair-*`, `ping-ping`, `clipboard-*`, `sms-*`; the relay's `relay-*` frames and `relay-rest` bodies; `push` bodies | `schemas/README.md` |
| `design-tokens/` | `tokens.json` (byte-identical to `../docs/design-system/tokens.json`), `type-extras.json` | `design-tokens/README.md` |
| `strings/` | `ui-strings.json`: every user-facing string in English and Vietnamese, with its JSON Schema | `strings/README.md` |
| `tools/vectors/` | `generate_vectors.py` (`--check`), `verify_vectors.py` | `tools/vectors/README.md` |
| `tools/schemas/` | `check_schemas.py` (schemas plus the examples in the hub docs; `HANDLIVE_DOCS_DIR`) | `tools/schemas/README.md` |
| `tools/strings/` | `check_strings.py` (catalog rules of 0.12.5; `--docs`, `--self-test`) | `strings/README.md` |
| `tools/bench/` | Clipboard latency and reconnect time from the `HLBENCH/1` logs of both devices; manual test on the device matrix | `tools/bench/README.md` |

```sh
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt -r tools/strings/requirements.txt
tools/.venv/bin/python tools/vectors/verify_vectors.py          # must print "0 lỗi" (0 errors)
tools/.venv/bin/python tools/vectors/generate_vectors.py --check # must print "0 lệch" (0 mismatches)
tools/.venv/bin/python tools/schemas/check_schemas.py           # must print "XANH" (green)
tools/.venv/bin/python tools/strings/check_strings.py           # must print "OK"
```

## License

Apache License 2.0 — see [LICENSE](LICENSE). Contributions follow [CONTRIBUTING](https://github.com/HandLive/.github/blob/main/CONTRIBUTING.md) (small commits under a real name, DCO sign-off with `git commit -s`); report vulnerabilities privately as described in [SECURITY](https://github.com/HandLive/.github/blob/main/SECURITY.md).
