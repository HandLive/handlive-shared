[English](README.md) | Tiếng Việt

# Test vector liên nền tảng (Kotlin ↔ Swift ↔ Rust)

Nguồn đặc tả: `docs/detailed-design/00-common-specs.md` (0.2, 0.3, 0.4.1, 0.4.3, 0.4.4, 0.5, 0.6), `02-pairing.md` (PAIR-01, PAIR-02) và `03-connectivity.md` (CONN-01, CONN-03, CONN-04). File do `tools/vectors/generate_vectors.py` sinh — **không sửa tay**; kiểm bằng `tools/vectors/verify_vectors.py`. Mọi khóa là giá trị test công khai (khóa RFC hoặc `SHA-256("HL-TEST|<nhãn>|<i>")`), không phải khóa thật.

## Quy ước chung

- Mỗi file: `{"description", "source", "vectors": [...], "invalid_vectors": [...]?}`. Mỗi vector có `name` (duy nhất trong file). Mọi file có ≥ 2 vector.
- `vectors`: phải tính ra đúng từng trường. `invalid_vectors` (vector âm): thao tác AEAD/MAC/kiểm chữ ký **phải thất bại**; trường `reason` ∈ `tag_mismatch`, `aad_mismatch`, `ciphertext_mismatch`, `payload_too_short`, `mac_mismatch`, `message_tampered`, `signature_mismatch`, `wrong_key`, `wrong_label`, `device_id_mismatch`, `signature_length`, `signature_not_canonical`, `key_mismatch`, `wrong_byte_order`, `wrong_encoding`, `wrong_field_order`, `wrong_pin`, `wrong_parameters`, `hint_outside_window`, `stale`, `not_b64`, và cho phép kiểm định tuyến của relay `bad_magic`, `unsupported_version`, `unknown_op`, `truncated`, `inner_not_hl`, `inner_too_short`, `bad_wrapper`, `not_paired`. Trong `pair-handshake.json` và `discovery-hint.json`, vector âm còn nêu phép kiểm phải thất bại và bằng chứng của lỗi (xem mục của hai file đó).
- Byte: hex chữ thường, không tiền tố. Số nguyên: số JSON. Chuỗi hiển thị/UTF-8: chuỗi JSON.
- Chuỗi wire giữ đúng dạng spec (0.3): `payload` của envelope là **b64** (RFC 4648 §4, có padding); `eph`, `nonce`, `mac` bên trong JSON là **b64u** (RFC 4648 §5, không padding); uuid 36 ký tự thường.
- Chuỗi JSON (plaintext, envelope) là dạng gọn (không khoảng trắng), giữ thứ tự khóa, UTF-8 không escape. Mã hóa phải dùng **đúng byte** của chuỗi trong vector; khi nhận, parse JSON chứ không so chuỗi.
- `direction`: `c2s` = Mac/iOS → Android (khóa `k_c2s`), `s2c` = Android → Mac/iOS (`k_s2c`). `key_source` chỉ ra khóa lấy từ vector nào (để test nối chuỗi); trường `key` luôn có đủ giá trị.
- HKDF = HKDF-SHA256. Khi spec không ghi salt → **salt rỗng** (≡ 32 byte 0).

## Diễn giải đã chốt cho chỗ spec chưa ghi rõ

| Chỗ | Chọn | Lý do |
|-----|------|-------|
| `T1`, `T2` (0.6.3) | Ghép **byte thô**: `"HL1|hello|"` (ASCII) ‖ `pair_id` 16 byte ‖ `device_id`C 16 byte ‖ `eph`C 32 byte ‖ `nonce`C 32 byte (= 106 byte). `T2` = `"HL1|welcome|"` ‖ `T1` ‖ `device_id`S 16 ‖ `eph`S 32 ‖ `nonce`S 32 (= 198 byte). Không dùng dạng chuỗi 36 ký tự hay b64u | Giống `T_offer` ở 02-pairing (ghép trường byte độ dài cố định) |
| MAC `HLSTREAM1` (0.6.3 bước 7) | `"HLSTREAM1|"` ‖ `session_id` 16 byte ‖ `nonce_c` 32 byte; welcome: `"HLSTREAM1|welcome|"` ‖ `session_id` 16 ‖ `nonce_c` 32 ‖ `nonce_s` 32 | Như trên |
| `info` của `K_stream` | Chuỗi UTF-8 `"handlive/v1/stream/<kênh>/<session_id 36 ký tự>"`, `<kênh>` = đoạn đường dẫn: `camera`, `call-audio` | `info` là văn bản; 07-call-audio ghi đúng dạng này |
| `K_auth` | HKDF(ikm = `PRK`, salt rỗng, info `"handlive/v1/session-auth"`, L = 32) | Spec không ghi salt, L |
| Salt của `PRK` | So `device_id` theo 16 byte, thứ tự byte không dấu (= so chuỗi uuid chữ thường) | |
| Rekey | `X25519(eph bên khởi tạo, eph bên nhận)`; ikm = shared ‖ `secret` cũ (64 byte); salt = SHA-256(`nonce` bên khởi tạo ‖ `nonce` bên nhận); `k_c2s` = 32 byte đầu, `k_s2c` = 32 byte sau theo vai C/S (không theo bên khởi tạo); kết quả 64 byte thay `secret` cho lần rekey sau. `epoch` không vào KDF | Spec ghi "hai nonce" không nói thứ tự |
| `K_stream` | Dẫn từ `secret` của bắt tay (epoch 0) trong vector | Spec chưa nói sau rekey dùng `secret` nào |
| Chuỗi MAC của `pair/confirm` (PAIR-01 API 4) | Nhãn confirm, rồi `T_offer` ‖ `pair_id` 16 byte ‖ `created_at` int64 BE ‖ `sig` 64 byte thô (không phải chuỗi b64u); mọi nhãn ghép nối là ASCII không dấu cách (liệt kê ở mục `pair-handshake.json`) | Spec ghi ở PAIR-01 API 4–5 từ hub d1f52c9; JSON không bao giờ được MAC |
| `str(x)` trong `T_offer` | uint16 BE số byte ‖ byte UTF-8 của chuỗi đúng như gửi trong JSON, **không chuẩn hóa Unicode** (`QR cặp 2` có tên điện thoại dạng NFD) | Spec ghi ở 0.6.2 từ hub d1f52c9 (không chuẩn hóa NFC/NFD) |
| `K_pin` (0.6.2) | Argon2id phiên bản 0x13, mật khẩu = UTF-8 của 6 ký tự chữ số (giữ số 0 đầu, không bao giờ đổi sang số nguyên), salt = `nonce_c` ‖ `nonce_s` (64 byte), không secret, không dữ liệu kèm | Spec ghi ở 0.6.2 từ hub d1f52c9 |
| URI QR (PAIR-01 API 1) | Dạng phía sinh: tham số theo thứ tự `v`, `pk`, `ps`, `d`, `rv`; `d` mã hóa phần trăm mọi byte UTF-8 ngoài tập unreserved của RFC 3986 thành `%XX` hex in hoa (dấu cách = `%20`, `&` = `%26`). Bên nhận parse URI chứ không so chuỗi | API 1 yêu cầu mã hóa phần trăm UTF-8 theo RFC 3986 (hub d1f52c9); thứ tự tham số và tập ký tự được mã hóa chỉ là dạng của phía sinh |
| Gợi ý khám phá (0.4.1) | Giờ = `floor(now_ms / 3 600 000)` (làm tròn xuống, kể cả số âm; giờ trước của giờ 0 là −1, int64 bù hai); hint = hex chữ thường; TXT `h` nối các hint bằng `,` không dấu cách; client chấp nhận giờ trước, giờ hiện tại và giờ sau theo đồng hồ của nó (chịu lệch tới một giờ theo cả hai chiều), liệt kê theo đúng thứ tự đó trong `accepted` | Tất cả có trong 0.4.1 từ hub d1f52c9, trừ thứ tự của `accepted` — chỉ là quy ước của vector (có thể so như tập hợp) |
| `K_push` (0.6.1) | HKDF(ikm = `PRK`, salt rỗng, info `"handlive/v1/push"`, L = 32); envelope của push mã hóa đúng như 0.5.1 và `env_b64`/`hl` là base64 chuẩn **có padding** của JSON envelope UTF-8 | 0.6.1 chỉ ghi info; 0.6.3 bước 8 chốt salt rỗng và L = 32; CONN-04 gọi đây là envelope "mã hóa bằng K_push" |
| Khung `HR` (0.4.3) | `device_id` = 16 byte thô; relay chỉ đổi 16 byte đó (đích → nguồn); lớp bọc văn bản giữ nguyên từng byte của `env` và phát lại dạng `{"from":…,"env":…}`; khung và lớp bọc sai dạng được trả bằng op `error` `BAD_REQUEST` của relay | 0.4.3 cho bố cục nhưng không nói cách xử lý lỗi, cũng không nói có serialize lại `env` hay không |
| Vector âm của `pair-handshake.json` | `check` là phép kiểm **đầu tiên** thất bại theo thứ tự của bên nhận trong spec: API 2 quy tắc 2 rồi 3 (`hello_key`, `hello_device_id`); API 3 quy tắc 3 (`offer_mac` → `offer_device_id` → `offer_tls`); API 4 quy tắc 1–2 và API 5 quy tắc 1 (MAC → `prk_check` → chữ ký) | Giá trị sai phải bị đúng phép kiểm nhắm tới bắt, không phải một phép kiểm trước đó |

## Từng file

### `xchacha20-poly1305.json`
AEAD_XChaCha20_Poly1305. `key` 32, `nonce` 24, `aad`, `plaintext`, `ciphertext` (cùng độ dài plaintext), `tag` 16. Trường phụ cho Apple: `hchacha20_subkey` = HChaCha20(key, nonce[0:16]); `chacha20_nonce` = `00000000` ‖ nonce[16:24]; ChaCha20-Poly1305(subkey, chacha20_nonce) phải cho đúng ciphertext ‖ tag. Vector 1 = draft-irtf-cfrg-xchacha-03 §A.3.1; còn lại tự sinh bằng libsodium. `invalid_vectors`: cùng trường, không có `plaintext`.

### `hchacha20.json`
`key` 32, `nonce` 16, `subkey` 32. Vector 1 = draft §2.2.1; vector 2 = input §A.3.1 (subkey tự tính, kiểm bằng libsodium); vector 3 tự sinh.

### `chacha20-poly1305.json`
AEAD_ChaCha20_Poly1305 nonce 12 byte (CryptoKit `ChaChaPoly`). RFC 8439 §2.8.2 (`nonce` = fixed-common `07000000` ‖ IV) và §A.5. Trường như XChaCha.

### `x25519.json`
`scalar` 32 (chưa clamp, hàm tự clamp), `u` 32, `output` 32. RFC 7748 §5.2 (2 vector) và §6.1 (khóa công khai Alice/Bob với `u` = 9, bí mật chung K từ hai phía).

### `hkdf-sha256.json`
`ikm`, `salt` (rỗng = `""`), `info`, `length` (byte), `prk` (extract), `okm`. RFC 5869 A.1–A.3.

### `device-id.json`
`ik_sig_seed` (khóa bí mật Ed25519 32 byte, RFC 8032 §7.1 TEST 1–3), `ik_sig_pub`, `sha256` = SHA-256(pub), `device_id_bytes` = 16 byte đầu sau khi đặt byte 6 = `(b & 0x0f) | 0x80`, byte 8 = `(b & 0x3f) | 0x80`, `device_id` = dạng uuid.

### `ed25519.json`
`seed` (khóa bí mật 32 byte), `public_key`, `message`, `signature` (64 byte R ‖ S): RFC 8032 §7.1 TEST 1–3, cùng khóa với `device-id.json`. Ký RFC 8032 là tất định nên bộ ký tất định tái tạo đúng `signature`; bộ ký có ngẫu nhiên (CryptoKit cố ý thêm ngẫu nhiên) cho ra chữ ký hợp lệ khác, nên bên cài đặt kiểm chữ ký của chính mình bằng phép kiểm chặt, không so từng byte. Cùng thuật toán với chữ ký attestation (PAIR-01) và chữ ký gửi relay (`relay-auth.json`). `invalid_vectors`: `{public_key, message, signature, reason}`, kiểm phải thất bại — thông điệp bị sửa (`message_tampered`), R hoặc S bị sửa (`signature_mismatch`), khóa khác (`wrong_key`), S thay bằng S + L (`signature_not_canonical`: thư viện kiểm lỏng sẽ chấp nhận; RFC 8032 §5.1.7 bắt S < L), chữ ký 63 byte (`signature_length`).

### `relay-auth.json`
`kind` = `register` (`POST /v1/devices`, CONN-03 API 1) hoặc `auth` (`POST /v1/auth/token`, 0.6.4, CONN-03 API 3). Trường chung: `ik_sig_seed`, `ik_sig_pub` (khóa RFC 8032 TEST 1–3), `device_id` (như `device-id.json`), `message`, `sig` (hex), `request` (body JSON trên dây, dạng gọn, b64u không padding). `register` thêm `platform` (`macos`, `android`, `ios`), `app_version`, `ts`; `message` = `"HLREG1"` ‖ device_id 16 byte ‖ ik_sig_pub 32 ‖ UTF-8(platform) ‖ ts int64 BE. `auth` thêm `challenge` (32 byte), `challenge_b64u`; `message` = `"HLAUTH1"` ‖ challenge ‖ device_id 16. `invalid_vectors`: `{kind, reason, ik_sig_pub, request}` (`auth` thêm `challenge` = giá trị relay đã cấp; `ik_sig_pub` là khóa relay lưu cho `device_id`), relay phải từ chối: `message_tampered` (ts, platform hoặc challenge đổi sau khi ký; `signed_message` là thông điệp đã ký thật), `device_id_mismatch` (chữ ký đúng nhưng `device_id` không dẫn xuất từ khóa), `wrong_label` (ký bằng nhãn kia), `wrong_key` (`signer_pub` là khóa đã ký), `signature_length` (400 `BAD_REQUEST`), `signature_not_canonical` (S + L); trừ `signature_length`, relay trả 401 `SIGNATURE_INVALID`.

### `pair-prk.json`
Hai cặp, một cặp `device_id` client nhỏ hơn, một cặp lớn hơn (`client_id_is_smaller`). `ik_dh` = khóa Alice/Bob RFC 7748 §6.1. `dh_shared` = X25519(ik_dh mình, ik_dh đối phương) (hai phía như nhau); `ikm` = `dh_shared` ‖ `pairing_secret` (64 byte); `salt_input` = id nhỏ ‖ id lớn (32 byte); `salt` = SHA-256(salt_input); `info` (chuỗi UTF-8), `length` = 32; `prk`.

### `pair-handshake.json`
Toàn bộ trao đổi PAIR-01 (API 1–5 và thân request của API 8) và Mã an toàn của PAIR-02, nối chuỗi từ `pair-prk.json` qua `keys_from`. Nhãn (ASCII, không dấu cách): `HL1|offer|`, `HL1|confirm|`, `HL1|done|`, `HL1|prk-check-c|`, `HL1|prk-check-s|`, `HLPAIR1`. `QR cặp 1` và `QR cặp 2` chính là cặp 1 và cặp 2 của `pair-prk.json` (cùng khóa, `pairing_secret` và `pair_id`, nên `prk` bằng giá trị trong `pair-prk.json`; `device_id` của client nhỏ hơn ở một cặp và lớn hơn ở cặp kia); `PIN cặp 3` dùng khóa của cặp 1 với `pair_id` mới và `K_pin` thay cho `pairing_secret`. Trường:
- Định danh: `client_*` và `android_*` = `ik_sig_seed`, `ik_sig_pub`, `device_id`, `ik_dh_priv`, `ik_dh_pub` (khóa RFC của `device-id.json` và `pair-prk.json`), `client_name`, `client_platform`, `client_model`, `android_name`, `android_model`, `android_os_version`; `tls_sha256` = 32 byte đại diện SHA-256 của chứng chỉ A-SVC (DER), giá trị client ghim và thấy trên kết nối LAN.
- QR (`mode` = `qr`; null ở chế độ PIN): `qr_uri` (≤ 300 ký tự; `QR cặp 2` có `rv` và tên chứa `&`), `qr_pk`, `qr_ps` (b64u như trong URI), `qr_rv` (hex hoặc null), `pr` = TXT `pr` = 8 chữ số hex thường đầu của SHA-256 trên 32 byte đã giải của `pk`, `pairing_secret`.
- PIN (`mode` = `pin`; null ở chế độ QR): `pin` (6 chữ số, có số 0 đầu), `argon2` = `{variant, version (19 = 0x13), t, m_kib, p, length}` của 0.6.2, `k_pin`.
- `nonce_c`, `nonce_s`; `secret` = `pairing_secret` hoặc `k_pin`; `k_pa_salt` (= `nonce_c` ‖ `nonce_s`), `k_pa_info`, `k_pa`.
- `t_offer` và `t_offer_parts` (`[{field, hex}]` theo thứ tự byte: `label`, `device_id_c`, `nonce_c`, `ik_sig_pub_c`, `ik_dh_pub_c`, `name_c`, `device_id_s`, `nonce_s`, `ik_sig_pub_s`, `ik_dh_pub_s`, `tls_sha256`, `name_s`; mỗi `name_*` là cả `str()`), `offer_mac`.
- `created_at`; `attestation` (127 byte) và `attestation_parts`; `sig_c`, `sig_s` = Ed25519 của client và của Android trên attestation (bộ ký tất định tái tạo đúng các byte đó; bộ ký có ngẫu nhiên như CryptoKit thì phải tạo chữ ký kiểm chặt đúng trên `attestation`, và MAC của confirm khi đó phủ chữ ký ấy); `security_code` = 8 chữ số hex thường đầu của SHA-256(`attestation`), giống nhau trên hai thiết bị.
- `confirm_mac_input` và các phần (`label`, `t_offer`, `pair_id`, `created_at`, `sig`), `confirm_mac`; `done_mac_input` và các phần (`label`, `pair_id`, `sig`), `done_mac`.
- `dh_shared`, `prk_ikm`, `prk_salt_input`, `prk_salt`, `prk_info`, `prk`; `prk_check_c_input`, `prk_check_c`, `prk_check_s_input`, `prk_check_s`.
- `hello_plaintext`, `offer_plaintext`, `confirm_plaintext`, `done_plaintext` (JSON `{op, data}`, khóa theo thứ tự bảng của spec, khóa, nonce, MAC và chữ ký dạng b64u) và `…_envelope` tương ứng (`type` = `pair`, `payload` = b64 của bản rõ, không mã hóa; `id` UUIDv7 mang `ts` ở 48 bit đầu). Đưa `hello_envelope` và `confirm_envelope` vào Android với định danh, `nonce_s` và `tls_sha256` của vector phải ra đúng `offer_plaintext` và `done_plaintext` (trừ `id`/`ts` của envelope).
- `pairs_request`: thân request `POST /v1/pairs` (API 8): `device_a` = Android, `device_b` = client, `attestation` dạng b64u, `sig_a` = `sig_s`, `sig_b` = `sig_c`.

`invalid_vectors`: `{name, vector, message, check, checked_by, reason, expected_error}`, thêm `plaintext` và `envelope` khi `message` có giá trị (thông điệp đó mang giá trị sai; mọi đầu vào khác lấy từ vector dương tên `vector`), thêm bằng chứng của lỗi. `check` là phép kiểm đầu tiên thất bại (xem bảng trên): `hello_key`, `hello_device_id` (Android), `offer_mac` (client), `confirm_mac`, `prk_check_c`, `sig_c` (Android), `done_mac`, `prk_check_s`, `sig_s` (client), `k_pin`, `pr` (`message` = null, cả hai bên). `checked_by` = `android`, `client` hoặc `both`. `expected_error` = mã của `pair/error`: `AUTH_FAILED`; `PIN_INVALID` khi MAC của offer sai ở chế độ PIN (A5) và khi `K_pin` sai; null với `pr` (chỉ là không tìm thấy điện thoại, E3). Lý do và bằng chứng:
- `mac_mismatch`, `signature_mismatch`: lật một bit; với chữ ký thì MAC được tính lại trên chữ ký đã sửa, nên chỉ phép kiểm chữ ký thất bại.
- `wrong_label`: nhãn chép kèm dấu cách từ `\|` của Markdown (`"HL1 | offer | "`, `confirm`, `done`; `mac_input`) hoặc nhãn `prk-check` của bên kia (`prk_check_input`).
- `wrong_byte_order`: độ dài `str()` little-endian (`mac_input`), `created_at` little-endian trong MAC của confirm (`mac_input`) hoặc trong attestation được ký (`signed_message`); salt của `K_pa` là `nonce_s ‖ nonce_c` (`mac_key`); salt của `PRK` = `device_id` lớn ‖ nhỏ (`prk_salt_input_used`, `prk_used`).
- `wrong_encoding`: `sig` ở dạng chuỗi b64u hoặc `pair_id` ở dạng chuỗi 36 ký tự trong MAC của confirm (`mac_input`); PIN bị đổi sang số nguyên nên mất số 0 đầu (`pin_used`, `k_pin_used`); `pr` băm chuỗi b64u của `pk` (`pr_input`).
- `wrong_field_order`: attestation được ký với `device_id` và khóa của client đứng trước Android (`signed_message`).
- `signature_not_canonical`: S thay bằng S + L (MAC tính lại).
- `message_tampered`: `tls_sha256` bị thay trên đường (MITM), MAC giữ nguyên; `mac_input` = `T_offer` gốc.
- `wrong_pin`: Android dẫn `K_pin` từ PIN người dùng gõ sai (`pin_used`, `k_pin_used`, `mac_key`); client trả lời bằng `client_reply_plaintext`/`client_reply_envelope` (`PIN_INVALID`, `attempts_left` = 2).
- `wrong_parameters`: `K_pin` với p = 1 (`argon2_used`, `k_pin_used`) — `crypto_pwhash` của libsodium không tính được KDF này (nó cố định p = 1 và salt 16 byte).
- `key_mismatch`: `ik_dh_pub` khác `pk` đã quét; `device_id_mismatch`: `device_id` không dẫn xuất từ `ik_sig_pub`.

### `discovery-hint.json`
Gợi ý TXT `h` (0.4.1, CONN-01 bước 3 và API 1–2) từ `prk` của `pair-prk.json`. `kind` = `key` (mỗi cặp của `pair-prk.json` một vector): `pair_id`, `prk_source`, `prk`, `info`, `length`, `k_disc`; `hours` = `[{hour, message, mac, hint}]` với `message` = `"HLDISC1"` ‖ giờ int64 BE, cho các giờ −1, 0, 1, 2 và 479762–479765; `clock` = `[{now_ms, hour, advertised, accepted}]`: giờ, gợi ý điện thoại quảng bá và các gợi ý client chấp nhận vào lúc đó (`[giờ trước, giờ này, giờ sau]`), tại 0, 3 599 999, 3 600 000, 1 727 150 000 123, 1 727 150 399 999 và 1 727 150 400 000. `kind` = `match`: điện thoại có các cặp `phone_pairs` quảng bá `txt_h` (theo đúng thứ tự đó) lúc `phone_now_ms` (`phone_hour`); client của `client_pair` lúc `client_now_ms` (`client_hour`) chấp nhận `accepted` và phải tìm thấy `matched_hint`; `matched_as` = `previous`, `current` hoặc `next` là giờ của điện thoại so với giờ của client. Kịch bản: cùng giờ; đồng hồ điện thoại chậm hơn và nhanh hơn 1 ms qua mốc giờ; chậm hơn và nhanh hơn đúng một giờ. `invalid_vectors`: `{name, pair, reason, client_now_ms, client_hour, txt_h}` kèm bằng chứng; client **không** được coi `txt_h` là khớp: `hint_outside_window` (`phone_now_ms`, `phone_hour`: giờ của điện thoại cách giờ của client hai giờ — nhanh hơn một giờ và 1 ms vượt hai mốc giờ, hoặc chậm hơn đúng hai giờ; 0.4.1 chỉ chấp nhận giờ trước, giờ hiện tại và giờ sau), `wrong_byte_order` (giờ int64 LE), `wrong_encoding` (giờ int32 BE), `wrong_label` (`"HLDISC1|"`), `wrong_key` (HMAC khóa bằng `PRK` thay vì `K_disc`, `mac_key`); `message` = các byte đã được MAC.

### `session-handshake.json`
Nối từ `pair-prk.json` theo `pair_id`. `k_auth`; `client_eph_priv/pub`, `client_nonce` (32); `t1`, `hello_mac` = HMAC-SHA256(k_auth, t1); `server_eph_*`, `server_nonce`, `t2`, `welcome_mac`; `eph_shared` = X25519(eph C, eph S); `secret_salt` = SHA-256(t2); `secret` (64) = HKDF(eph_shared ‖ prk, secret_salt, `"handlive/v1/session"`, 64); `k_c2s` = secret[0:32], `k_s2c` = secret[32:64]. `hello_plaintext`/`welcome_plaintext`: JSON `{op, data}` với `eph`/`nonce`/`mac` dạng b64u; `hello_envelope`/`welcome_envelope`: envelope `type = session`, `payload` = b64 của plaintext (chưa mã hóa). `invalid_vectors`: `{key, message, mac}` — HMAC(key, message) so hằng thời gian với `mac` phải **khác**.

### `session-rekey.json`
Epoch 1 (client khởi tạo, `secret_old` = `secret` bắt tay cặp 1) và epoch 2 (server khởi tạo, `secret_old` = `secret_new` của epoch 1). `initiator_*`/`responder_*` (eph priv/pub, nonce), `eph_shared`, `ikm` (96 byte), `salt_input` (64 byte), `salt`, `info`, `length` = 64, `secret_new`, `k_c2s`, `k_s2c`. `request_plaintext` = plaintext của `session/rekey`; `ack_data` = `data` của `ack` (bên nhận).

### `stream-keys.json`
Kênh `camera` (từ bắt tay cặp 1) và `call-audio` (cặp 2). `secret`, `info`, `length` = 96, `k_stream` = `k_auth`(32) ‖ `k_c2s`(32) ‖ `k_s2c`(32); `nonce_c`, `nonce_s` (32); `hello_message`/`hello_mac`, `welcome_message`/`welcome_mac`; envelope `stream_hello`/`stream_welcome` (`envelope_type` = `camera` hoặc `call_audio`, payload chưa mã hóa). `invalid_vectors` như file bắt tay (có ca đảo thứ tự hai nonce).

### `envelope.json`
`encrypted` = true: `key`, `v`, `type`, `id`, `ts`, `aad` (chuỗi `"<v>|<type>|<id>|<ts>"`), `aad_hex`, `plaintext` (JSON), `nonce` 24, `ciphertext`, `tag` 16, `payload_b64` = b64(nonce ‖ ciphertext ‖ tag), `envelope` (chuỗi wire). `encrypted` = false (tin bắt tay): `key`/`aad`/`nonce`/`ciphertext`/`tag` = null, `payload_b64` = b64(UTF-8 của `plaintext`). `invalid_vectors`: `{key, envelope}` — bên nhận dựng AAD từ chính các trường của envelope rồi giải mã, phải thất bại (tag sai, `ts`/`type` bị sửa, payload < 40 byte).

### `ack.json`
Như envelope mã hóa, `type = ack`, thêm `re`, `ok`. Có ack ok có `data`, ack ok `data` rỗng, ack lỗi `SMS_NO_SERVICE` (`error.code`, `message`, `details`).

### `clipboard-chunk.json`
Như envelope mã hóa nhưng plaintext nhị phân: `plaintext_hex` = `hdr_len` (uint16 BE) ‖ `header_json` (UTF-8) ‖ `chunk_data`. Thêm `transfer_id`, `index`, `header_json`, `hdr_len` (byte của JSON), `chunk_data`. Byte đầu plaintext là `0x00`. Khối trong vector ngắn hơn `CHUNK_SIZE` cho gọn.

### `hl-frame.json`
`channel`, `direction`, `key`, `seq`, `ts` (uint32), `header` (11 byte = `484c01` ‖ seq BE ‖ ts BE = AAD), `plaintext`, `nonce`, `ciphertext`, `tag`, `encrypted_part` = nonce ‖ ciphertext ‖ tag, `frame` = header ‖ encrypted_part. Kênh camera thêm `track`, `flags`, `pts_us` (int64 BE), `data` (plaintext = track ‖ flags ‖ pts_us ‖ data). Một vector dùng `seq` = `ts` = 2³²−1 để kiểm biên. `invalid_vectors`: `{key, frame}` — `seq` bị sửa (AAD sai), tag sai.

### `push-envelope.json`
Thứ điện thoại gửi cho iPhone/iPad không có phiên (CONN-04 bước 5b, API 2–4; SMS-02 API 2; CALL-01 API 4) và thứ phần mở rộng dịch vụ thông báo giải mã.
- `kind = "key"` (cả hai cặp của `pair-prk.json`): `pair_name`, `pair_id`, `prk_source`, `prk`, `salt` (rỗng), `info` = `"handlive/v1/push"`, `length` = 32, `k_push` = HKDF-SHA256(`PRK`, salt rỗng, info, 32).
- `kind = "envelope"` (cặp 2, client là iPhone của `relay-auth.json`): các trường của một vector mã hóa trong `envelope.json` với khóa `k_push` (`v`, `type`, `id`, `ts`, `aad`, `aad_hex`, `plaintext`, `nonce`, `ciphertext`, `tag`, `payload_b64`, `envelope`), thêm `sender_device_id` (điện thoại), `recipient_device_id` (iPhone), `env_b64` = base64 chuẩn có padding của chuỗi UTF-8 `envelope`, `reason`, `push_request` (thân `POST /v1/push`), `apns_payload` (thứ relay gửi APNs: `loc-key` = `push.<reason>`, `hl` = `env_b64`, `p` = `pair_id`) và `apns_headers`. Nội dung: một `sms/new` tiếng Việt, một `sms/new` từ tên người gửi không có trong danh bạ và không có SIM, một `call_event/state` đổ chuông (`time-sensitive`, `thread-id` `calls`). Plaintext của push không bao giờ có `local_id`.
- Giải mã như I-NSE: đọc `p` và `hl`, dẫn xuất `K_push` từ `PRK` của cặp đó, giải `hl` (base64 chuẩn, nghiêm ngặt) ra JSON envelope, dựng lại AAD từ `v`, `type`, `id`, `ts` đã parse, rồi giải mã.
- `invalid_vectors`: `{pair_id, key, env_b64}` kèm bằng chứng — `wrong_key` (K_push của cặp kia, chính `PRK`, `K_disc`), `tag_mismatch`, `aad_mismatch` (`ts` hoặc `type` bị sửa sau khi mã hóa; mã hóa với AAD viết có khoảng trắng, ghi ở `aad_used`), `stale` (giải mã được nhưng `received_at_ms` cách `ts` hơn 24 h: CONN-04 E7), `not_b64` (base64url không padding).
- Vector không chốt cách điện thoại cắt ngắn SMS dài khi push (xem báo cáo S2.3).

### `relay-frame.json`
Định tuyến qua relay (0.4.3, CONN-03 API 6), dùng device_id của cặp 1 (Mac `client_device_id`, điện thoại `android_device_id`).
- `kind = "frame"`: `direction` (`device_to_relay`: `device_id` = đích; `relay_to_device`: `device_id` = nguồn), `magic` = `4852` ("HR"), `ver` = 1, `op` = 1 (`op_name` `forward`), `device_id`, `device_id_hex`, `header` (20 byte), `inner_source` (vector của `hl-frame.json`), `inner` (khung HL nguyên vẹn), `frame` = header ‖ inner, `length`.
- `kind = "rewrite"`: `outbound` (từ bên gửi) và `inbound` (tới bên nhận) chỉ khác nhau ở 16 byte device_id.
- `kind = "text_rewrite"`: `outbound` `{"to", "env"}` (khóa theo thứ tự bất kỳ, có thể có khoảng trắng) thành `inbound` = `{"from":"<bên gửi>","env":<env>}` với `env` giữ nguyên từng byte như khi nhận (`env`); một ca dạng gọn, một ca `env` đứng trước, có khoảng trắng và `env` thụt dòng.
- `invalid_vectors` kèm lỗi relay phải trả (`expected_error`): khung (`kind = "frame"`) — `bad_magic`, `unsupported_version`, `unknown_op`, `truncated` (19 byte; có header mà không có khung HL), `inner_not_hl`, `inner_too_short` (dưới 11 + 24 + 16 byte) → `BAD_REQUEST`; lớp bọc văn bản (`kind = "text"`) — `bad_wrapper` (có cả `to` và `from`, `to` không phải device_id, thiếu `env`) → `BAD_REQUEST`, `not_paired` (`to` = chính bên gửi) → `NOT_PAIRED`.

### `envelope-roundtrip.json` (liên nền tảng, Android ghi)
Envelope do Android (`android/core/crypto`, Tink XChaCha20-Poly1305) mã hóa bằng khóa cố định của `envelope.json` (`k_c2s`/`k_s2c` cặp 1), `id` UUIDv7 và nonce ngẫu nhiên mới. **Cùng trường với vector `encrypted = true` của `envelope.json`** (`name`, `encrypted`, `direction`, `key`, `key_source`, `v`, `type`, `id`, `ts`, `aad`, `aad_hex`, `plaintext`, `nonce`, `ciphertext`, `tag`, `payload_b64`, `envelope`). Không sinh bằng `tools/vectors/`: chỉ ghi lại khi chạy `cd android && HL_WRITE_ROUNDTRIP=1 ./gradlew :core:crypto:test`; test thường chỉ đọc và giải mã lại. Phía Apple (M0.1) giải mã từng `envelope` bằng `key` và so với `plaintext`. Ngược lại, test Android giải mã `envelope-roundtrip-apple.json` nếu file đó có.

### `envelope-roundtrip-apple.json` (liên nền tảng, Apple ghi)
Envelope do Apple (`apple/Packages/HLCrypto`: HChaCha20 tự cài + CryptoKit `ChaChaPoly`) mã hóa bằng khóa cố định của `envelope.json` (`k_c2s`/`k_s2c` cặp 1), `id` UUIDv7 và nonce ngẫu nhiên mới; plaintext lấy nguyên byte từ các vector `encrypted = true` của `envelope.json`. Cùng trường và thứ tự trường như `envelope-roundtrip.json`. Không sinh bằng `tools/vectors/`: chỉ ghi lại khi chạy `cd apple/Packages/HLCrypto && HL_WRITE_ROUNDTRIP=1 swift test` (thêm `HL_SWIFT_TESTING_PACKAGE=1` nếu máy chỉ có Command Line Tools); test thường chỉ đọc và giải mã lại. Android (A0.1) và relay giải mã từng `envelope` bằng `key` và so với `plaintext`.

## Dùng trong CI

Mỗi nền tảng đọc thẳng các file này trong test đơn vị: tính lại mọi trường của `vectors`, và kiểm mọi `invalid_vectors` bị từ chối. Trên Apple, `xchacha20-poly1305.json` phải qua bằng HChaCha20 tự cài + `ChaChaPoly`.
