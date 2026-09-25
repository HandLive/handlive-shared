[English](README.md) | Tiếng Việt

# handlive-shared

Kho này không chạy ứng dụng. Nó giữ test vector, JSON Schema và design token để Android, Apple và relay đối chiếu cùng một hợp đồng. Các kho kia đọc qua `../shared`.

Nguồn: `../docs/detailed-design/00-common-specs.md` và `../docs/design-system/` của kho hub. Công cụ Python trong `tools/` sinh và kiểm các file này. Xem `CLAUDE.md` của kho này.

| Thư mục | Nội dung | Tài liệu |
|---------|----------|----------|
| `test-vectors/` | 14 file vector (RFC + tự sinh) và `envelope-roundtrip{,-apple}.json` liên nền tảng | `test-vectors/README.md` |
| `schemas/` | JSON Schema 2020-12: envelope, payload, ack, error, `session-*`, `capability-*` | `schemas/README.md` |
| `design-tokens/` | `tokens.json` (giống byte với `../docs/design-system/tokens.json`), `type-extras.json` | `design-tokens/README.md` |
| `tools/vectors/` | `generate_vectors.py` (`--check`), `verify_vectors.py` | `tools/vectors/README.md` |
| `tools/schemas/` | `check_schemas.py` (schema + ví dụ trong tài liệu hub; `HANDLIVE_DOCS_DIR`) | `tools/schemas/README.md` |

```sh
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt
tools/.venv/bin/python tools/vectors/verify_vectors.py          # phải in "0 lỗi"
tools/.venv/bin/python tools/vectors/generate_vectors.py --check # phải in "0 lệch"
tools/.venv/bin/python tools/schemas/check_schemas.py           # phải in "XANH"
```

## Giấy phép

Apache License 2.0 — xem [LICENSE](LICENSE). Đóng góp theo [CONTRIBUTING](https://github.com/HandLive/.github/blob/main/CONTRIBUTING.vi.md) (commit nhỏ, đứng tên người thật, ký DCO bằng `git commit -s`); báo lỗi bảo mật kín theo [SECURITY](https://github.com/HandLive/.github/blob/main/SECURITY.vi.md).
