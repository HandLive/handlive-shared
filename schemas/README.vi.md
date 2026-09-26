[English](README.md) | Tiếng Việt

# JSON Schema giao thức HandLive

JSON Schema draft 2020-12 cho khung tin thiết bị ↔ thiết bị, khung WebSocket và thân REST của relay, và thân push, sinh từ `docs/detailed-design/00-common-specs.md` (0.3, 0.4.3, 0.4.4, 0.5.1, 0.6.3, 0.7.1–0.7.4, 0.8.1–0.8.3) và đặc tả chi tiết PAIR-01…03, CONN-01…04, CLIP-01…04, SMS-01…05. Android (`core/protocol`), Apple (`HLProtocol`) và relay dùng làm nguồn đối chiếu trong test.

`$id` = `https://handlive.app/schemas/v1/<file>`: chỉ là định danh, không tải qua mạng. `$ref` giữa các file dùng đường dẫn tương đối (`common.schema.json#/$defs/uuid-v7`), nên nạp cả thư mục vào registry của thư viện validator.

| File | Đối tượng | Nguồn |
|------|-----------|-------|
| `common.schema.json` | Chỉ `$defs`: `uuid`, `uuid-v4` (`pair_id`), `uuid-v7` (`id`, `re`), `uuid-v8` (`device_id`), `int32`, `int64`, `timestamp`, `b64`, `b64u`, `b64u-16` (`rv_id`), `b64u-32`, `b64u-64` (chữ ký Ed25519), `ws-close-code` (mã đóng WebSocket), `platform` | 0.2, 0.3, 0.8.3 |
| `envelope.schema.json` | Envelope `{v, type, id, ts, payload}`; `$defs/type` = enum `type` | 0.5.1, 0.7.1 |
| `payload.schema.json` | Plaintext chung `{op, data}` | 0.5.1 |
| `ack.schema.json` | Plaintext ack; `$defs/success`, `$defs/failure` | 0.5.1 |
| `error.schema.json` | `ack.error` `{code, message, details?}`; `$defs/code` = enum mã lỗi | 0.8.1 |
| `session-hello.schema.json` | `session/hello` | 0.6.3; CONN-01 API 4 |
| `session-welcome.schema.json` | `session/welcome` | 0.6.3; CONN-01 API 5 |
| `session-error.schema.json` | `session/error` | 0.6.3; CONN-01 API 6 |
| `session-rekey.schema.json` | `session/rekey`; `$defs/ack` = ack thành công mang `{epoch, eph, nonce}` | 0.6.3; CONN-02 API 3 |
| `session-bye.schema.json` | `session/bye` | 0.7.1; PAIR-03 API 2 |
| `capability-hello.schema.json` | `capability/hello`; `$defs/capability-data` dùng chung | 0.7.2 |
| `capability-update.schema.json` | `capability/update` (cùng `data` với hello) | 0.7.2 |
| `pair-hello`, `pair-offer`, `pair-confirm`, `pair-done`, `pair-error` `.schema.json` | Bắt tay ghép nối (payload không mã hóa) | 0.6.2; PAIR-01 API 2–6 |
| `pair-revoke.schema.json` | `pair/revoke`; `$defs/ack` = ack thành công có `data` rỗng | PAIR-03 API 1 |
| `ping-ping.schema.json` | `ping/ping` qua relay; `$defs/ack` = `{seq, server_ts}` | CONN-02 API 2 |
| `clipboard-push.schema.json` | `clipboard/push` (văn bản gửi thẳng hoặc `transfer`); `$defs/ack` = `{clip_id, status, reason?}` | CLIP-01 API 5, CLIP-03 API 3, CLIP-04 API 4 |
| `clipboard-conflict.schema.json`, `clipboard-cancel.schema.json` | `clipboard/conflict`, `clipboard/cancel` | CLIP-01 API 6, CLIP-03 API 5 |
| `sms-common.schema.json` | Chỉ `$defs`: đối tượng `thread` và `message`, `synced-message` (không `local_id`), `unread-entry`, `message-key`, `thread-id`, `address`, `sub-id` | SMS-01 API 1 |
| `sms-sync.schema.json`, `sms-history.schema.json` | `sms/sync`, `sms/history`; `$defs/ack` = trang dữ liệu trả về | SMS-01 API 1, SMS-03 API 1 |
| `sms-new.schema.json`, `sms-status.schema.json`, `sms-read_changed.schema.json` | `sms/new` (cả envelope của push), `sms/status`, `sms/read_changed` | SMS-02 API 1, SMS-04 API 2, SMS-05 API 1 |
| `sms-send.schema.json` | `sms/send`; `$defs/ack` = `{accepted, parts}` | SMS-04 API 1 |
| `sms-notification.schema.json` | Nội dung thông báo SMS mới trên Mac/iOS (định danh và `userInfo`) — cục bộ, không phải tin trên dây | SMS-02 API 4 |
| `relay-wrapper.schema.json` | Lớp bọc định tuyến trên `/v1/relay`: `$defs/outbound` `{to, env}`, `$defs/inbound` `{from, env}` | 0.4.3; CONN-03 API 6 |
| `relay-presence`, `relay-error`, `relay-rv_join`, `relay-rv_joined`, `relay-rv_msg`, `relay-pair_revoked` `.schema.json` | Tin điều khiển relay `{op, …}` (không E2E, không có `data`) | 0.7.3; CONN-03 API 5, PAIR-01 API 7, PAIR-03 API 4 |
| `relay-rest.schema.json` | Chỉ `$defs`: mọi thân yêu cầu và phản hồi REST của relay (`devices-request` … `push-response`), `error-response` và `error-code` | 0.7.4, 0.8.2 |
| `push.schema.json` | Chỉ `$defs`: `fcm-data`, `fcm-request`, `fcm-response`, `apns-payload` | 0.4.4; CONN-04 API 3–4 |

Catalog chuỗi giao diện có schema riêng bên cạnh: `../strings/ui-strings.schema.json`.

## Cách dùng

1. Kiểm envelope bằng `envelope.schema.json`.
2. Giải mã `payload` (tin bắt tay `session` hello/welcome/error: chỉ giải base64).
3. `type = ack` → `ack.schema.json` (hoặc `<op>#/$defs/ack` nếu op có data ack riêng, ví dụ `session-rekey`, `sms-sync`); `type` khác → `<type>-<op>.schema.json` nếu có, không thì `payload.schema.json`.

Trên `/v1/relay`: khung văn bản có `op` là tin điều khiển relay → `relay-<op>.schema.json`; khung văn bản có `to`/`from` là lớp bọc định tuyến → `relay-wrapper.schema.json` (`env` bên trong là envelope, xử lý như trên). Thân REST và thân push là `$defs` của `relay-rest.schema.json` và `push.schema.json` (`relay-rest.schema.json#/$defs/push-request`). Khung nhị phân `HR` không phải JSON: xem `../test-vectors/relay-frame.json`.

## Quy ước chặt

Schema kiểm **tin do bên gửi phát ra** (test của từng nền tảng validate tin mình sinh). Bên nhận không dùng schema để từ chối: theo 00-common-specs 0.5.1 quy tắc 6, trường lạ bị bỏ qua và giá trị enum lạ không làm hỏng tin.

- `v` = 1; `type` đúng 10 giá trị của 0.7.1; `id`, `re` là UUIDv7 chữ thường 36 ký tự (nibble version `7`, variant `8|9|a|b`); `device_id` UUIDv8, `pair_id` UUIDv4.
- `ts` int64 ≥ 0; `payload` Base64 chuẩn có padding; `eph`, `nonce`, `mac` là b64u đúng 32 byte (43 ký tự, dạng chuẩn tắc).
- `additionalProperties: false` ở mọi đối tượng mà spec liệt kê đủ trường, gồm cả từng tính năng trong `features`.
- Capability: chỉ `enabled` bắt buộc trong mỗi tính năng; trường ghi "Chỉ Android/Mac/iOS" là tùy chọn. `bt_address` dạng `A1:B2:C3:D4:E5:F6` (hoa, dấu hai chấm, theo ví dụ AUDIO-01) hoặc `null`.
- `session/error`: `code` ∈ {`AUTH_FAILED`, `PAIR_UNKNOWN`, `PAIR_REVOKED`, `UNSUPPORTED_VERSION`, `RATE_LIMITED`}; `min_protocol` bắt buộc khi và chỉ khi `code = UNSUPPORTED_VERSION`.
- Mã đóng WebSocket (`common.schema.json#/$defs/ws-close-code`) đúng bảng 0.8.3, kể cả 4410 `REKEY_FAILED`, 4411 `IDLE_TIMEOUT`, 4429 `RATE_LIMITED`; `check_schemas.py` so với bảng.
- SMS: tin trong ack của `sms/sync` hoặc `sms/history` không bao giờ có `local_id`; ack đồng bộ có `page_token` khi và chỉ khi `has_more = true`, và chỉ trang cuối có `unread` (mục có `unread_count ≥ 1`); `sms/send` có đúng một người nhận và nội dung 1–1 600 ký tự, không chỉ toàn khoảng trắng; `sms/status` có `error_code` (một trong bốn lỗi gửi) khi và chỉ khi `status = failed`.
- Bảng nhớ tạm: có đúng một trong hai `text`, `transfer`; ảnh cần `transfer`, `width`, `height` và MIME ảnh; `chunk_size` = 65 536; ack `ignored` có `reason`.
- Relay: `rv_id` là b64u của đúng 16 byte (22 ký tự); `rv_msg` chỉ mang envelope `pair`; op `error` của relay dùng `NOT_PAIRED`, `NOT_CONNECTED`, `PAYLOAD_TOO_LARGE`, `RATE_LIMITED`, `BAD_REQUEST`; thân lỗi REST dùng mã của 0.8.2 (so với bảng), không có `details`; chữ ký là b64u đúng 64 byte; attestation là b64u của 127 byte bắt đầu bằng `HLPAIR1`; `expires_in` = 900.
- Push: `kind = wake` đi với `user_open`, `sms_send`, `call_action` và không có `env_b64`; `kind = alert` đi với `sms_new`, `call_incoming`, `call_missed` và có `env_b64` (≤ 3 000 ký tự, b64 của JSON envelope mã hóa bằng `K_push`); FCM chỉ mang `{t, p, r}`; alert APNs chỉ có `loc-key` thuộc nhóm `push` của catalog chuỗi giao diện (so với CONN-04 API 4 và catalog), `time-sensitive` chỉ cho `push.call_incoming`.

Thêm op hoặc mã lỗi: sửa `00-common-specs.md` trước, rồi schema, rồi chạy `tools/.venv/bin/python tools/schemas/check_schemas.py` (xem `tools/schemas/README.vi.md`).
