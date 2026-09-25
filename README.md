English | [Tiếng Việt](README.vi.md)

# handlive-shared

This repository runs no app. It holds the contract that Android, Apple and the relay all check against: test vectors, JSON Schemas and design tokens. The other repositories read it through `../shared`.

Sources: `../docs/detailed-design/00-common-specs.md` and `../docs/design-system/` in the hub repository. The Python tools in `tools/` generate and check these files. See this repository's `CLAUDE.md`.

| Folder | Contents | Docs |
|--------|----------|------|
| `test-vectors/` | 14 vector files (RFC and generated) plus the cross-platform `envelope-roundtrip{,-apple}.json` | `test-vectors/README.md` |
| `schemas/` | JSON Schema 2020-12: envelope, payload, ack, error, `session-*`, `capability-*` | `schemas/README.md` |
| `design-tokens/` | `tokens.json` (byte-identical to `../docs/design-system/tokens.json`), `type-extras.json` | `design-tokens/README.md` |
| `tools/vectors/` | `generate_vectors.py` (`--check`), `verify_vectors.py` | `tools/vectors/README.md` |
| `tools/schemas/` | `check_schemas.py` (schemas plus the examples in the hub docs; `HANDLIVE_DOCS_DIR`) | `tools/schemas/README.md` |

```sh
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt
tools/.venv/bin/python tools/vectors/verify_vectors.py          # must print "0 lỗi" (0 errors)
tools/.venv/bin/python tools/vectors/generate_vectors.py --check # must print "0 lệch" (0 mismatches)
tools/.venv/bin/python tools/schemas/check_schemas.py           # must print "XANH" (green)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE). Contributions follow [CONTRIBUTING](https://github.com/HandLive/.github/blob/main/CONTRIBUTING.md) (small commits under a real name, DCO sign-off with `git commit -s`); report vulnerabilities privately as described in [SECURITY](https://github.com/HandLive/.github/blob/main/SECURITY.md).
