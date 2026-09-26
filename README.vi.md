[English](README.md) | Tiếng Việt

# handlive-shared

Kho này không chạy ứng dụng. Kho lưu test vector, JSON Schema, design token và catalog chuỗi giao diện. Android, Apple và relay dùng chung các file này. Các kho kia đọc qua `../shared`.

Nguồn: `../docs/detailed-design/00-common-specs.md` và `../docs/design-system/` trên kho hub. Công cụ Python trong `tools/` sinh và kiểm các file này. Xem `CLAUDE.md` trong kho này.

| Thư mục | Nội dung | Tài liệu |
|---------|----------|----------|
| `test-vectors/` | 18 file vector (RFC + tự sinh) và `envelope-roundtrip{,-apple}.json` liên nền tảng | `test-vectors/README.vi.md` |
| `schemas/` | JSON Schema 2020-12: envelope, payload, ack, error, `session-*`, `capability-*` | `schemas/README.vi.md` |
| `design-tokens/` | `tokens.json` (giống byte với `../docs/design-system/tokens.json`), `type-extras.json` | `design-tokens/README.vi.md` |
| `strings/` | `ui-strings.json`: mọi chuỗi hiển thị bằng tiếng Anh và tiếng Việt, kèm JSON Schema | `strings/README.vi.md` |
| `tools/vectors/` | `generate_vectors.py` (`--check`), `verify_vectors.py` | `tools/vectors/README.vi.md` |
| `tools/schemas/` | `check_schemas.py` (schema + ví dụ trong tài liệu hub; `HANDLIVE_DOCS_DIR`) | `tools/schemas/README.vi.md` |
| `tools/strings/` | `check_strings.py` (quy tắc catalog 0.12.5; `--docs`, `--self-test`) | `strings/README.vi.md` |
| `tools/bench/` | Độ trễ bảng nhớ tạm và thời gian kết nối lại từ log `HLBENCH/1` của hai thiết bị; kiểm thử tay theo ma trận thiết bị | `tools/bench/README.vi.md` |

```sh
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt -r tools/strings/requirements.txt
tools/.venv/bin/python tools/vectors/verify_vectors.py          # phải in "0 lỗi"
tools/.venv/bin/python tools/vectors/generate_vectors.py --check # phải in "0 lệch"
tools/.venv/bin/python tools/schemas/check_schemas.py           # phải in "XANH"
tools/.venv/bin/python tools/strings/check_strings.py           # phải in "OK"
```

## Giấy phép

Apache License 2.0 — xem [LICENSE](LICENSE). Đóng góp theo [CONTRIBUTING](https://github.com/HandLive/.github/blob/main/CONTRIBUTING.vi.md) (commit nhỏ, đứng tên người thật, ký DCO bằng `git commit -s`); báo lỗi bảo mật kín theo [SECURITY](https://github.com/HandLive/.github/blob/main/SECURITY.vi.md).
