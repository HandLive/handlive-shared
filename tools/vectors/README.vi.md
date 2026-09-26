[English](README.md) | Tiếng Việt

# tools/vectors — sinh và kiểm test vector mã hóa

Chạy từ gốc kho `shared/` (handlive-shared); venv tại `tools/.venv` của kho này.

Đầu ra: `shared/test-vectors/*.json` (mô tả trường trong `shared/test-vectors/README.vi.md`).

| Script | Việc | Chạy |
|--------|------|------|
| `generate_vectors.py` | Sinh lại toàn bộ file vector từ giá trị cố định; `--check` so byte-exact với file hiện có, lệch thì exit 1 | `tools/.venv/bin/python tools/vectors/generate_vectors.py [--check]` — `--check` phải in `0 lệch` |
| `verify_vectors.py` | Kiểm mọi vector (kể cả RFC) và mọi vector âm bằng thư viện độc lập với phía sinh; XChaCha20 kiểm hai đường (libsodium và HChaCha20 + ChaCha20-Poly1305); Argon2id bằng argon2-cffi (bản C tham chiếu của PHC) đối chiếu Argon2id của OpenSSL ở phía sinh | `tools/.venv/bin/python tools/vectors/verify_vectors.py` — phải in `0 lỗi` |

Cài (từ gốc `shared/`): `python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/vectors/requirements.txt -r tools/schemas/requirements.txt`.

Mô-đun:

| File | Vai trò |
|------|---------|
| `rfc_source_values.py` | Giá trị chép nguyên văn từ draft-irtf-cfrg-xchacha-03, RFC 8439, 7748, 5869, 8032 (đã đối chiếu với bản .txt tải từ rfc-editor.org / ietf.org; ba chữ ký RFC 8032 §7.1 còn được `cryptography` và libsodium tái tạo đúng) |
| `handlive_protocol_derivations.py` | Phép dẫn xuất HandLive phía sinh (`cryptography` + pynacl), `test_bytes(label)`, thông điệp `HLREG1`/`HLAUTH1` |
| `pairing_discovery_derivations.py` | Phép dẫn xuất PAIR-01/PAIR-02 và gợi ý khám phá phía sinh, chỉ dùng `cryptography` (`T_offer`, chuỗi MAC, attestation, `K_pa`, `K_pin` bằng Argon2id của OpenSSL, URI QR, `pr`, `K_disc`, hint) |
| `pair_handshake_messages.py` | Bản rõ và envelope `pair/*` của `pair-handshake.json` |
| `hchacha20_reference.py` | HChaCha20 thuần Python (đường Apple) |
| `build_*_vectors.py` | Dựng nội dung từng file vector (`build_signature_vectors.py`: `ed25519.json`, `relay-auth.json`; `build_pair_handshake_vectors.py` + `build_pair_handshake_negative_vectors.py`: `pair-handshake.json`; `build_discovery_hint_vectors.py`: `discovery-hint.json`; `build_push_relay_vectors.py`: `push-envelope.json`, `relay-frame.json`) |
| `verify_common.py`, `verify_*_checks.py` | Phía kiểm: HKDF/HMAC bằng `hashlib`/`hmac`, X25519/Ed25519/XChaCha bằng libsodium; vector chữ ký âm được kiểm đúng lý do ghi trong `reason` |
| `verify_pairing_common.py`, `verify_pair_handshake_checks.py`, `verify_pair_handshake_negative_checks.py`, `verify_discovery_hint_checks.py` | Kiểm ghép nối và khám phá: `T_offer`, chuỗi MAC và attestation dựng lại từ các trường JSON của thông điệp `pair`, Argon2id bằng argon2-cffi, phép kiểm của bên nhận chạy theo thứ tự spec nên mỗi vector âm thất bại đúng ở `check` của nó vì đúng `reason` |
| `verify_push_relay_checks.py` | `K_push` bằng `hashlib`/`hmac` nối chuỗi với `pair-prk.json`; envelope của push giải như phần mở rộng dịch vụ thông báo và giải mã hai đường; khung `HR` tách bằng `struct`, khung HL bên trong so với `hl-frame.json` và giải mã; đổi lớp bọc văn bản kiểm bằng bộ quét JSON cấp ngoài cùng giữ nguyên văn bản `env`; mỗi vector âm thất bại đúng vì `reason` của nó |

Sửa định dạng hay thêm vector: sửa `build_*`, chạy `generate_vectors.py`, rồi `verify_vectors.py`. Không sửa tay file JSON.
