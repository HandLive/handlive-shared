[English](README.md) | Tiếng Việt

# JSON Schema giao thức HandLive

JSON Schema draft 2020-12 cho khung tin thiết bị ↔ thiết bị, khung WebSocket và thân REST của relay, và thân push, sinh từ `docs/detailed-design/00-common-specs.md` (0.3, 0.4.3, 0.4.4, 0.5.1, 0.6.3, 0.7.1–0.7.4, 0.8.1–0.8.3) và đặc tả chi tiết PAIR-01…03, CONN-01…04, CLIP-01…04, SMS-01…05, CALL-01…05, WEB-01…05. Android (`core/protocol`), Apple (`HLProtocol`) và relay dùng làm nguồn đối chiếu trong test.

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
| `sms-send.schema.json` | `sms/send`; `$defs/ack` = `{accepted, parts}`, `$defs/ack-failure` = ack lỗi với các mã của nó (`RATE_LIMITED` mang `details.retry_after_ms`) | SMS-04 API 1 |
| `sms-notification.schema.json` | Nội dung thông báo SMS mới trên Mac/iOS (định danh và `userInfo`) — cục bộ, không phải tin trên dây | SMS-02 API 4 |
| `call_event-common.schema.json` | Chỉ `$defs`: `call-id`, `number`, `display-name`, `sub-id`, `entry-id`, `call-type` và mục nhật ký cuộc gọi `entry` | CALL-01 API 1, CALL-04 |
| `call_event-state.schema.json` | `call_event/state` (cả envelope của push `call_incoming`, và của `call_missed` khi không có nhật ký) | CALL-01 API 1 |
| `call_event-action.schema.json` | `call_event/action`; `$defs/ack` = ack thành công có `data` rỗng, `$defs/ack-failure` = ack lỗi kèm mã và chi tiết | CALL-02 API 1, CALL-03 API 1 |
| `call_event-log_sync.schema.json` | `call_event/log_sync`; `$defs/ack` = trang dữ liệu trả về, `$defs/ack-failure` | CALL-04 API 1 |
| `call_event-log_new.schema.json` | `call_event/log_new` (cả envelope của push `call_missed`) | CALL-04 API 2 |
| `call_event-app_call.schema.json` | `call_event/app_call` (không ack, không bao giờ đi trong push); `$defs/app-call-data` | CALL-05 API 1 |
| `call-notification.schema.json` | Nội dung thông báo cuộc gọi đến và cuộc gọi nhỡ trên Mac/iOS, `$defs/incoming` và `$defs/missed` (định danh, danh mục, `userInfo`) — cục bộ, không phải tin trên dây | CALL-01 API 6–7, CALL-04 API 4 |
| `web-active.schema.json` | `web/active` (hai chiều, không ack); `$defs/browser` = enum id trình duyệt | 0.7.1; WEB-01 API 1 |
| `web-inactive.schema.json` | `web/inactive` (hai chiều, không ack) | 0.7.1; WEB-01 API 2 |
| `relay-wrapper.schema.json` | Lớp bọc định tuyến trên `/v1/relay`: `$defs/outbound` `{to, env}`, `$defs/inbound` `{from, env}` | 0.4.3; CONN-03 API 6 |
| `relay-presence`, `relay-error`, `relay-rv_join`, `relay-rv_joined`, `relay-rv_msg`, `relay-pair_revoked` `.schema.json` | Tin điều khiển relay `{op, …}` (không E2E, không có `data`) | 0.7.3; CONN-03 API 5, PAIR-01 API 7, PAIR-03 API 4 |
| `relay-rest.schema.json` | Chỉ `$defs`: mọi thân yêu cầu và phản hồi REST của relay (`devices-request` … `push-response`, `devices-delete-request` với các mục `revocation`), `error-response` và `error-code` | 0.7.4, 0.8.2 |
| `push.schema.json` | Chỉ `$defs`: `fcm-data`, `fcm-request`, `fcm-response`, `apns-payload` | 0.4.4; CONN-04 API 3–4 |

Catalog chuỗi giao diện có schema riêng bên cạnh: `../strings/ui-strings.schema.json`.

## Cách dùng

1. Kiểm envelope bằng `envelope.schema.json`.
2. Giải mã `payload` (tin bắt tay `session` hello/welcome/error: chỉ giải base64).
3. `type = ack` → `ack.schema.json` (hoặc `<op>#/$defs/ack` nếu op có data ack riêng, ví dụ `session-rekey`, `sms-sync`, và `<op>#/$defs/ack-failure` cho ack lỗi của op có đặc tả liệt kê mã lỗi và chi tiết, ví dụ `call_event-action`); `type` khác → `<type>-<op>.schema.json` nếu có, không thì `payload.schema.json`. `call_event/hfp_status` chưa có schema: các trường của nó được đặc tả cùng âm thanh cuộc gọi (AUDIO-02 API 3).

Trên `/v1/relay`: khung văn bản có `op` là tin điều khiển relay → `relay-<op>.schema.json`; khung văn bản có `to`/`from` là lớp bọc định tuyến → `relay-wrapper.schema.json` (`env` bên trong là envelope, xử lý như trên). Thân REST và thân push là `$defs` của `relay-rest.schema.json` và `push.schema.json` (`relay-rest.schema.json#/$defs/push-request`). Khung nhị phân `HR` không phải JSON: xem `../test-vectors/relay-frame.json`.

## Quy ước chặt

Schema kiểm **tin do bên gửi phát ra** (test của từng nền tảng validate tin mình sinh). Bên nhận không dùng schema để từ chối: theo 00-common-specs 0.5.1 quy tắc 6, trường lạ bị bỏ qua và giá trị enum lạ không làm hỏng tin.

- `v` = 1; `type` đúng 11 giá trị của 0.7.1; `id`, `re` là UUIDv7 chữ thường 36 ký tự (nibble version `7`, variant `8|9|a|b`); `device_id` UUIDv8, `pair_id` UUIDv4.
- `ts` int64 ≥ 0; `payload` Base64 chuẩn có padding; `eph`, `nonce`, `mac` là b64u đúng 32 byte (43 ký tự, dạng chuẩn tắc).
- `additionalProperties: false` ở mọi đối tượng mà spec liệt kê đủ trường, gồm cả từng tính năng trong `features`.
- Capability: chỉ `enabled` bắt buộc trong mỗi tính năng; trường ghi "Chỉ Android/Mac/iOS" là tùy chọn. `bt_address` dạng `A1:B2:C3:D4:E5:F6` (hoa, dấu hai chấm, theo ví dụ AUDIO-01) hoặc `null`.
- `session/error`: `code` ∈ {`AUTH_FAILED`, `PAIR_UNKNOWN`, `PAIR_REVOKED`, `UNSUPPORTED_VERSION`, `RATE_LIMITED`}; `min_protocol` bắt buộc khi và chỉ khi `code = UNSUPPORTED_VERSION`.
- Mã đóng WebSocket (`common.schema.json#/$defs/ws-close-code`) đúng bảng 0.8.3, kể cả 4410 `REKEY_FAILED`, 4411 `IDLE_TIMEOUT`, 4429 `RATE_LIMITED`; `check_schemas.py` so với bảng.
- SMS: tin trong ack của `sms/sync` hoặc `sms/history` không bao giờ có `local_id`; ack đồng bộ có `page_token` khi và chỉ khi `has_more = true`, và chỉ trang cuối có `unread` (mục có `unread_count ≥ 1`); `sms/send` có đúng một người nhận và nội dung 1–1 600 ký tự, không chỉ toàn khoảng trắng; `sms/status` có `error_code` (một trong bốn lỗi gửi) khi và chỉ khi `status = failed`; thông báo SMS dùng category `HL_SMS`, hoặc `HL_SMS_GROUP` cho cuộc trò chuyện nhiều địa chỉ, và với push thì I-NSE đặt `threadIdentifier` sau khi giải mã.
- Cuộc gọi: `call_event/state` luôn có đủ mọi trường (null ở chỗ được phép); `ended_at` và `end_reason` có giá trị đúng khi `state = idle`; có số đúng khi `presentation = allowed`, có tên thì phải có số; `waiting = true` chỉ khi `state = ringing`, không có cuộc gọi chờ thì `waiting_*` là null; ngữ cảnh cuộc gọi đi có `presentation = unknown`, ngữ cảnh gọi đi và không rõ chiều không có `answered_at` và chỉ kết thúc bằng `ended`; cuộc gọi đến đang `offhook`, có cuộc gọi chờ hoặc kết thúc bằng `ended` thì có `answered_at`, cuộc gọi đang đổ chuông không có cuộc gọi chờ hoặc kết thúc bằng `missed`, `rejected`, `answered_elsewhere` thì không có; `controls.answer` và `reject` cần `ringing` không có cuộc gọi chờ (`answer` kéo theo `reject`), `end` cần `offhook`, `hold` và `dtmf` là `hfp` đúng khi `offhook` và `hfp_connected`, `mute` đúng khi thêm `audio_on = mac`. `call_event/action` chỉ có `audio` khi là `answer`; ack lỗi của nó dùng mã của CALL-02 API 1 cộng `INTERNAL`, kèm `details.action` (`CALL_HFP_REQUIRED`), `details.permission` = `android.permission.ANSWER_PHONE_CALLS` (`PERMISSION_MISSING`) và `details` `{state, reason}` (`CALL_ACTION_NOT_ALLOWED`; `waiting` và `platform` chỉ khi đang đổ chuông, `system` khi đang đổ chuông hoặc đang gọi). `call_event/log_sync` nhận `limit` 1–500 và trả tối đa 500 mục kèm `cursor`, `has_more`, `reset`; `entry_id` ≥ 1, `duration_s` ≥ 0. Thông báo cuộc gọi dùng `threadIdentifier` `calls` (cuộc gọi nhỡ là `calls:<pair_id>` trừ khi do push tạo), danh mục `HL_CALL_INCOMING`, `HL_CALL_INCOMING_MAC`, `HL_CALL_MISSED` (danh mục cuối chỉ khi có số), định danh `call_id` (Mac) và `call-missed:<pair_id>:<entry_id|call_id>`; danh mục của thông báo cuộc gọi đến chỉ được đặt khi thông báo có nút hành động (Mac `HL_CALL_INCOMING_MAC` khi `controls.answer` và `controls.reject` đều là true, iPhone/iPad `HL_CALL_INCOMING` khi `controls.reject` là true), nên nội dung không có nút thì không có danh mục; cuộc gọi đến ở mức `passive` hoặc `timeSensitive`, chỉ push hiện muộn hơn 60 s sau `started_at` (CALL-01 E7) ở mức `active`, không có danh mục và không có định danh riêng. Chỉ thông báo trên Mac ở mức `timeSensitive` (chế độ Tập trung ẩn panel, CALL-01 API 7) có `sound` `default`, nhận ra qua định danh hoặc danh mục của Mac; thông báo passive trên Mac và nội dung trên iPhone/iPad không đặt âm (push của chúng đã mang âm, CONN-04 API 4).
- Cuộc gọi ứng dụng (CALL-05): `call_event/app_call` luôn có đủ mọi trường (null ở chỗ được phép); `app.package` là tên gói Android (≤ 255 ký tự, có ít nhất một dấu chấm), `app.label` dài 1–64 ký tự, `caller` dài 1–128 ký tự hoặc null; `state` ∈ {`ringing`, `ongoing`, `ended`}; `audio` luôn là `phone`; `ended_at` và `end_reason` có giá trị đúng khi `state = ended`; `controls.answer` và `decline` cần `ringing`, `end` cần `ongoing`; cuộc gọi đang đổ chuông, hoặc đã kết thúc là `declined`, `missed`, `unknown`, không có `answered_at`. Với `call_id` của cuộc gọi ứng dụng, ack lỗi của `call_event/action` còn có thể mang `CALL_ROUTE_FAILED` (`answer` với `audio = mac`) và `CALL_APP_ACTION_UNAVAILABLE`, không bắt buộc `details`; `features.call.app_calls` là trường boolean không bắt buộc của capability.
- Duyệt web tiếp: `page_id` là UUIDv7; `url` bắt đầu bằng `http://` hoặc `https://` rồi đến một ký tự của host, dài tối đa 8 192 ký tự (`WEB_URL_MAX` là 8 KiB UTF-8: bên gửi và bên nhận kiểm thêm độ dài theo byte trong code, việc JSON Schema không làm được); `title` dài 1–256 ký tự hoặc vắng mặt; `browser` là một id trong bảng trình duyệt của 0.7.1 (`other` cho trình duyệt khác); `web/inactive` chỉ mang `page_id`. `features.web` bắt buộc có `enabled`, `send` và `receive` (mọi nền tảng gửi đủ ba trường; iPhone/iPad gửi `send = false`).
- Bảng nhớ tạm: có đúng một trong hai `text`, `transfer`; ảnh cần `transfer`, `width`, `height` và MIME ảnh; `chunk_size` = 65 536; ack `ignored` có `reason`.
- Relay: `rv_id` là b64u của đúng 16 byte (22 ký tự); thu hồi mang câu thu hồi `HLREVOKE1` (`revoked_at`, `sig`: `pair_revoked`, thân yêu cầu thu hồi, mỗi mục `revocations[]` của `DELETE /v1/devices/me?revoke_pairs=true`; `GET /v1/pairs` trả `revoked_by` và `revoke_sig` cho cặp đã thu hồi, `revoke_sig` null với cặp bị thu hồi trước khi có câu thu hồi có chữ ký); `rv_msg` chỉ mang envelope `pair`; op `error` của relay dùng `NOT_PAIRED`, `NOT_CONNECTED`, `PAYLOAD_TOO_LARGE`, `RATE_LIMITED`, `BAD_REQUEST`, và `BAD_REQUEST` không bao giờ mang `to` (không bao giờ lặp lại một id sai dạng); thân lỗi REST dùng mã của 0.8.2 (so với bảng), không có `details`; chữ ký là b64u đúng 64 byte; attestation là b64u của 127 byte bắt đầu bằng `HLPAIR1`; `expires_in` = 900.
- Push: `kind = wake` đi với `user_open`, `sms_send`, `call_action` và không có `env_b64`; `kind = alert` đi với `sms_new`, `call_incoming`, `call_missed` và có `env_b64` (≤ 3 000 ký tự, b64 của JSON envelope mã hóa bằng `K_push`); FCM chỉ mang `{t, p, r}`; alert APNs chỉ có `loc-key` thuộc nhóm `push` của catalog chuỗi giao diện (so với CONN-04 API 4 và catalog), `time-sensitive` chỉ cho `push.call_incoming`; `thread-id` APNs là nhóm chung `sms` hoặc `calls`; `collapse_key` là ASCII in được không có khoảng trắng (0x21–0x7E), 1–64 ký tự: `message_key` cho `sms_new` (`sms:12847`), `call:<call_id>` cho `call_incoming`, `call:<call_id>` hoặc `calllog:<entry_id>` cho `call_missed`; `ttl_s` trong khoảng 0–86 400, và điện thoại gửi 86 400 với `sms_new` và `call_missed`, 30 với `call_incoming`; FCM `android.ttl` tối đa `"60s"` và `android.collapse_key` luôn là `wake`.

Thêm op hoặc mã lỗi: sửa `00-common-specs.md` trước, rồi schema, rồi chạy `tools/.venv/bin/python tools/schemas/check_schemas.py` (xem `tools/schemas/README.vi.md`).
