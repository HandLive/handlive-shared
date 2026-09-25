[English](README.md) | Tiếng Việt

# tools/vectors — sinh và kiểm test vector mã hóa

Chạy từ gốc kho `shared/` (handlive-shared); venv tại `tools/.venv` của kho này.

Đầu ra: `shared/test-vectors/*.json` (mô tả trường trong `shared/test-vectors/README.vi.md`).

| Script | Việc | Chạy |
|--------|------|------|
| `generate_vectors.py` | Sinh lại toàn bộ file vector từ giá trị cố định; `--check` so byte-exact với file hiện có, lệch thì exit 1 | `tools/.venv/bin/python tools/vectors/generate_vectors.py [--check]` — `--check` phải in `0 lệch` |
| `verify_vectors.py` | Kiểm mọi vector (kể cả RFC) và mọi vector âm bằng thư viện độc lập với phía sinh; XChaCha20 kiểm hai đường (libsodium và HChaCha20 + ChaCha20-Poly1305) | `tools/.venv/bin/python tools/vectors/verify_vectors.py` — phải in `0 lỗi` |

Cài (từ gốc `shared/`): `python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt`.

Mô-đun:

| File | Vai trò |
|------|---------|
| `rfc_source_values.py` | Giá trị chép nguyên văn từ draft-irtf-cfrg-xchacha-03, RFC 8439, 7748, 5869, 8032 (đã đối chiếu với bản .txt tải từ rfc-editor.org / ietf.org; ba chữ ký RFC 8032 §7.1 còn được `cryptography` và libsodium tái tạo đúng) |
| `handlive_protocol_derivations.py` | Phép dẫn xuất HandLive phía sinh (`cryptography` + pynacl), `test_bytes(label)`, thông điệp `HLREG1`/`HLAUTH1` |
| `hchacha20_reference.py` | HChaCha20 thuần Python (đường Apple) |
| `build_*_vectors.py` | Dựng nội dung từng file vector (`build_signature_vectors.py`: `ed25519.json`, `relay-auth.json`) |
| `verify_common.py`, `verify_*_checks.py` | Phía kiểm: HKDF/HMAC bằng `hashlib`/`hmac`, X25519/Ed25519/XChaCha bằng libsodium; vector chữ ký âm được kiểm đúng lý do ghi trong `reason` |

Sửa định dạng hay thêm vector: sửa `build_*`, chạy `generate_vectors.py`, rồi `verify_vectors.py`. Không sửa tay file JSON.
