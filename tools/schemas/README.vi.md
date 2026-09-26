[English](README.md) | Tiếng Việt

# Kiểm JSON Schema

Chạy từ gốc kho `shared/` (handlive-shared). Ví dụ được đọc từ `docs/detailed-design/` của kho hub — mặc định là thư mục cha của `shared/` trong workspace, ghi đè bằng `HANDLIVE_DOCS_DIR`.

```sh
tools/.venv/bin/python -m pip install -r tools/schemas/requirements.txt   # nếu venv chưa có
tools/.venv/bin/python tools/schemas/check_schemas.py
```

Thoát 0 khi xanh (in `XANH`). Các bước:

1. Mọi `shared/schemas/*.schema.json` hợp lệ theo metaschema draft 2020-12, `$id` khớp tên file, mọi `$ref` phân giải được; enum mã lỗi khớp bảng 0.8.1, enum mã đóng WebSocket khớp bảng 0.8.3 và enum `type` khớp bảng 0.7.1 (đọc thẳng từ `00-common-specs.md`). `relay_sms_spec_checks.py` kiểm thêm: các op `sms` và op nào ack có data (0.7.1), các op điều khiển relay (0.7.3, mỗi op một file `relay-<op>`), các endpoint REST của relay và thân `relay-rest` của từng endpoint (0.7.4), mã lỗi relay (0.8.2), enum `reason` của push (CONN-04 API 2) và enum `loc-key` của APNs (CONN-04 API 4) — mỗi `loc-key` cũng phải là khóa iOS trong `strings/ui-strings.json`.
2. Ví dụ trong `docs/detailed-design/`:
   - `00-common-specs.md`: **mọi** khối ```json phải phân loại được và qua schema; `{op, data}` ngoài mục session/capability kiểm bằng `payload.schema.json`.
   - `01`–`08` (cả hai bản ngôn ngữ): kiểm mọi envelope (`v` + `type`), mọi ack (`re` + `ok`; dùng ack riêng của op nếu có, theo tiêu đề `WS <type>/<op>`) và mọi `{op, data}` nằm dưới tiêu đề `WS <type>/<op>` có schema `<type>-<op>` (`session`, `capability`, `pair`, `ping`, `clipboard`, `sms`). Envelope `session` có payload giải base64 ra JSON thì kiểm cả plaintext bắt tay. Khung relay nhận theo hình dạng (`{op, …}` không có `data` → `relay-<op>`, `{to|from, env}` → `relay-wrapper`, `{error}` → `relay-rest#error-response`), thân REST và push theo tiêu đề mục API (`POST /v1/devices`, `FCM HTTP v1`, `APNs HTTP/2`…) và các trường, nội dung thông báo SMS theo danh mục `HL_SMS`. `env_b64` của `POST /v1/push` và `hl` của payload APNs phải giải ra một envelope hợp lệ. Đối tượng chưa có schema (op camera, cuộc gọi, âm thanh cuộc gọi của các phase sau) chỉ đếm.
   - Khối ```json không parse cả khối thì parse từng dòng; dòng không parse được là lỗi tài liệu. Trong khối ```http, mỗi dòng bắt đầu bằng `{` là một thân JSON. Inline code chỉ tính khi là JSON hợp lệ.
3. Mẫu dương tự viết (`sample_messages.py`, `sample_messages_sms.py`, `sample_messages_relay.py`) phải qua; mẫu âm (mỗi mẫu làm hỏng đúng một chỗ: thiếu trường, sai `v`, `type` lạ, mã lỗi lạ, uuid sai dạng, b64 sai, push đánh thức kèm nội dung…) phải bị từ chối.
4. Đoạn catalog chuỗi giao diện trích trong 0.12.1 (khối ```jsonc có `strings`) qua `strings/ui-strings.schema.json` và các quy tắc của `tools/strings/catalog_rules.py`, trừ thứ tự khóa.
5. Tin trên dây trong `shared/test-vectors` qua schema của chúng: `request` của `relay-auth.json`, `pairs_request` và plaintext `pair/*` của `pair-handshake.json`.

## Quy tắc thay placeholder

Placeholder là chuỗi dạng `"<...>"` (ví dụ `"<b64>"`, `"<id của yêu cầu>"`), chuỗi chứa `…` (ví dụ `"…"`, `"0192f4a0-…"`) hoặc đúng `"..."`. Thay theo **tên khóa** chứa nó, và in ra mỗi lần thay:

| Khóa | Giá trị thay |
|------|--------------|
| `id`, `re` | `01920000-0000-7000-8000-000000000000` (UUIDv7) |
| `pair_id` | `00000000-0000-4000-8000-000000000000` (UUIDv4) |
| `device_id` | `00000000-0000-8000-8000-000000000000` (UUIDv8) |
| `payload` | Base64 có padding của 40 byte 0 (nonce 24 + tag 16) |
| `eph`, `nonce`, `mac`, `prk_check` | b64u không padding của 32 byte 0 |
| `sig`, `sig_a`, `sig_b` | b64u không padding của 64 byte 0 |
| `attestation` | b64u của `HLPAIR1` theo sau là 120 byte 0 (127 byte, 0.6.2) |
| `access_token` | Một JWS dạng gọn (ba phần b64u) |
| `token` | 64 chữ số thập lục phân 0 (token APNs, cũng là chuỗi token FCM hợp lệ) |
| `env_b64`, `hl` | Base64 của một JSON envelope `{v, type: sms, id, ts, payload}` |
| `by` | `00000000-0000-8000-8000-000000000000` (UUIDv8) |
| `code`, `message` | `BAD_REQUEST` (mã có trong cả 0.8.1 và 0.8.2), `diagnostic` |

Placeholder ở khóa khác → lỗi, không bỏ qua.

## Known spec issues

`KNOWN_SPEC_ISSUES` trong `doc_examples.py` liệt kê ví dụ trong tài liệu sai so với chính đặc tả, kèm lý do (không sửa `docs/` từ công cụ này). Mục đó phải tiếp tục hỏng; khi tài liệu được sửa và ví dụ qua, script báo lỗi để xóa mục khỏi danh sách.
