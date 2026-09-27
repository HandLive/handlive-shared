[English](README.md) | Tiếng Việt

# Relay cục bộ

Relay đám mây của HandLive cùng mọi thứ nó cần, chạy trên một máy phát triển, để kiểm thử đầu cuối các ứng dụng thật. Điện thoại trên máy ảo Android gọi tới relay như gọi tới `relay.example.com`. Mọi push relay gửi cho Apple hay Google đều được ghi vào tệp capture thay vì gửi đi.

| Thành phần | Địa chỉ | Ghi chú |
|------------|---------|---------|
| PostgreSQL | `127.0.0.1:55433` | PostgreSQL 18 của Homebrew (`HANDLIVE_PG_BIN`), cụm tạm trong thư mục trạng thái, tắt Unix socket, thông tin đăng nhập dev của `relay/.env.example` |
| Redis | `127.0.0.1:56380` | Không lưu xuống đĩa (`HANDLIVE_REDIS_SERVER`) |
| Relay | `http://127.0.0.1:18080` | `relay/target/debug/relay-server` (cargo build khi chưa có hoặc khi có `--build`); migration chạy lúc khởi động; mỗi lần khởi động một `RELAY_JWT_SECRET` mới, chỉ nằm trong môi trường của tiến trình; `RELAY_TRUSTED_PROXIES=127.0.0.1` |
| TLS front | `https://127.0.0.1:18443`, từ máy ảo là `https://10.0.2.2:18443` | `tls_front.py`: một CA thử và chứng chỉ máy chủ cho 10.0.2.2, 127.0.0.1, localhost; thêm `X-Forwarded-For` như reverse proxy khi triển khai thật |
| APNs giả | `http://127.0.0.1:18444`, sandbox ở `/sandbox` | `mock_apns.py`: HTTP/2 prior knowledge, đúng cách client của relay nói với URL cục bộ; kiểm provider token ES256 |
| FCM giả | `http://127.0.0.1:18445` | `mock_fcm.py`: `messages:send` và endpoint token OAuth mà tệp service account trỏ tới; kiểm assertion RS256 và access token |

Cổng cố định theo thư mục trạng thái, lấy từ lần `up` đầu tiên, vì bản build Android ghi cứng cổng của TLS front vào APK. Thư mục trạng thái (`--state-dir`, không có thì `$HANDLIVE_RELAY_STACK_DIR`, không có nữa thì `$TMPDIR/handlive-relay-stack`) chứa khóa sinh ra, dữ liệu, log, capture và `relay_stack.json`. Thư mục này không bao giờ nằm trong một kho mã. Khóa và chứng chỉ sinh tại đó, chỉ dùng với TLS front và các máy chủ giả, không bao giờ commit.

## Cách dùng

```sh
tools/.venv/bin/python -m pip install -r tools/e2e/relay_stack/requirements.txt
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py up          # in endpoint, pin, tệp capture
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py check       # health forward push: mỗi dòng PASS hoặc FAIL
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py check android --wait-s 60
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py captures --provider apns --prk <PRK hex của cặp>
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py status      # thoát 1 khi có tiến trình không chạy
tools/.venv/bin/python tools/e2e/relay_stack/relay_stack.py down        # --wipe xóa luôn dữ liệu, log, capture
tools/.venv/bin/python tools/e2e/relay_stack/self_test.py               # các thành phần, không cần dịch vụ (CI)
```

`up` ghi mọi thứ client cần vào `<state-dir>/relay_stack.json`: URL của relay (thường, TLS, WebSocket, từ máy ảo), tệp CA và biến môi trường cho client Python (`SSL_CERT_FILE`), SPKI pin và tham số Gradle của bản build Android, topic, key id và team id APNs, URL và tệp capture của máy chủ giả, URL PostgreSQL và các tệp log.

| Kiểm tra | Điều kiện PASS |
|----------|----------------|
| `health` | Relay lắng nghe sau khi chạy migration; `_sqlx_migrations` có mọi tệp của `relay/migrations`; Redis trả lời; relay trả lời qua TLS front (chứng chỉ kiểm bằng CA); các máy chủ giả đang lắng nghe |
| `forward` | `tools/bench/relay_load.py` đi qua TLS front: thiết bị giả đăng ký (HLREG1), xác thực (HLAUTH1), ghép cặp, mở `/v1/relay`; mọi wrapper văn bản và frame nhị phân `HR` tới được peer (CONN-03 API 6) |
| `push` | Thiết bị giả gửi `POST /v1/push`: `call_incoming`, `sms_new`, `call_missed` tới APNs giả đúng CONN-04 API 4 (header, `loc-key`, `thread-id`, `interruption-level`, `apns-collapse-id`, `apns-expiration`, `hl` giữ nguyên từng byte, mở được bằng `K_push` của cặp); wake tới FCM giả đúng API 3, wake thứ hai bị gộp; token chết cho 409 và bị xóa (E3) |
| `android` | Dòng của ứng dụng thật trong `devices`, và trong log của TLS front với User-Agent của OkHttp: `POST /v1/devices`, challenge và token (JWT), `GET /v1/relay 101`; presence trong Redis; các cặp của nó |

Log không bao giờ chứa payload. Relay ghi đường dẫn, mã trạng thái, kích thước, thời gian. TLS front ghi địa chỉ client, method, đường dẫn không kèm query, mã trạng thái, phiên bản TLS, User-Agent. Capture chứa đúng những gì nhà cung cấp push nhận được, trừ thông tin xác thực. Các kiểm tra chỉ in type và op của `hl` đã giải mã, không in số điện thoại hay nội dung.

## Ứng dụng Android

```sh
tools/e2e/relay_stack/build_android_for_local_relay.sh --serial emulator-5554 \
    --patch pins-without-port --patch debug-trust
```

Script xuất cây `android/` đã commit ra cạnh liên kết tới `../shared` và `../docs`, build `:app:assembleFossDebug` với `-Phandlive.relayHost=10.0.2.2:18443 -Phandlive.relayExtraPins=<pin>` chỉ trên dòng lệnh, rồi cài APK bằng `adb install -r` (ứng dụng giữ dữ liệu, service tự chạy lại nhờ `MY_PACKAGE_REPLACED`). Script không đụng tới `android/` hay thư mục build của nó.

Không có hai bản vá, ứng dụng hiện tại không dùng được relay này:

- **pins-without-port** — `OkHttpRelayTransport` thêm pin cho nguyên chuỗi `RELAY_HOST`. Host có cổng không phải mẫu hợp lệ của `CertificatePinner`: `IllegalArgumentException: Invalid pattern: 10.0.2.2:18443`. Mọi tác vụ relay nuốt lỗi này nên không yêu cầu nào tới relay, và mở Cài đặt làm ứng dụng crash (luồng trạng thái relay). Relay cục bộ hiếm khi có cổng 443 (macOS chỉ cho người dùng thường mở cổng này trên mọi giao diện, và cổng thường đã bị chiếm), nên cần cổng riêng. Bản vá pin theo tên host của URL.
- **debug-trust** — ứng dụng chỉ tin CA hệ thống, kiểm trước cả pin: TLS front ghi `TLS handshake failed: SSLV3_ALERT_CERTIFICATE_UNKNOWN`. Bản vá thêm network security config chỉ cho bản debug (`debug-overrides`), tin thêm CA của relay cục bộ, chép vào bản xuất thành `res/raw/local_relay_ca.pem`. OkHttp vẫn kiểm pin.

Ứng dụng đăng ký thiết bị khi service khởi động và relay đang bật. Ứng dụng chỉ xin token (challenge → HLAUTH1 → JWT) khi có việc với relay: đăng ký cặp mới, gửi push. Ứng dụng vào `/v1/relay` theo các yêu cầu ở bước 2 của CONN-03: service khởi động khi có cặp đã đăng ký relay mà chưa có phiên, phiên LAN kết thúc không có `session/bye`, SMS hay cuộc gọi đang đổ chuông cho client không có phiên, điểm hẹn ghép nối.

## Dùng với client giả của `tools/e2e/`

1. `relay_stack.py up`, rồi build và cài ứng dụng với cả hai bản vá (ở trên).
2. Đăng ký client giả với relay trước khi ghép nối: `stack_rest.FakeDevice(platform, seed)` với seed Ed25519 của client, gọi `register(...)` (HLREG1, rồi HLAUTH1). Điện thoại đăng ký cặp ngay sau khi ghép nối. Nếu client chưa đăng ký, điện thoại nhận 404 và chờ 24 giờ (PAIR-01 API 8 logic 6).
3. Ghép nối bằng PIN qua LAN (`adb forward`). Sau đó ứng dụng gọi `/v1/auth/challenge`, `/v1/auth/token` và `POST /v1/pairs` (201).
4. Đường relay: bỏ phiên LAN mà không gửi `session/bye`, ứng dụng sẽ mở `/v1/relay`. Mở `wss://127.0.0.1:18443/v1/relay` bằng JWT của client (CA trong `SSL_CERT_FILE`), đọc `presence`, rồi chạy phiên `/v1/ctl` bằng wrapper `{"to", "env"}` (0.4.3).
5. Đường push: ghép nối một iPhone giả (`platform ios`), gửi token bằng `PUT /v1/devices/me/push-token` (`provider` `apns_sandbox`, `topic` `app.handlive.ios`, token dạng hex; token bắt đầu bằng `dead` nhận 410). Khi iPhone không có phiên, gửi SMS hoặc gọi tới máy ảo (`adb emu sms send`, `adb emu gsm call`, chỉ dùng số giả): ứng dụng gửi `POST /v1/push`, và `captures --provider apns --prk <PRK>` cho thấy push đó cùng type và op của envelope đã giải mã.
6. `check android` tổng hợp những gì ứng dụng đã làm.

Những chỗ dễ vấp:

- Giữ phiên của client mở vài giây. Ứng dụng ghi capability của client một cách bất đồng bộ và bỏ việc ghi khi phiên kết thúc. Phiên đóng ngay sau `capability/hello` để lại capability rỗng, và khi đó ứng dụng không gửi push nào cho iPhone đó.
- Thu hồi cặp khi ứng dụng đang ở `/v1/relay`, hoặc hủy ghép nối trên điện thoại. Nếu thiết bị giả thu hồi cặp rồi tự xóa khỏi relay (`DELETE /v1/devices/me`), dòng của cặp cũng bị xóa. Ứng dụng đang offline sẽ không bao giờ nhận `pair_revoked` và giữ cặp đó cho LAN.
- APK tin CA của một thư mục trạng thái. Hãy dùng lại cùng `--state-dir` (`down --wipe` giữ nguyên khóa). Thư mục trạng thái mới là CA mới, cần build lại.
- Mạng của máy ảo đôi khi rớt (`IpReachabilityMonitor … NUD_FAILED` trong logcat). Khi đó ứng dụng kết nối lại `/v1/relay`, log của TLS front ghi một dòng `101` mới.

Sau `down` rồi `up`, relay có JWT secret mới. Ứng dụng hiện tại giữ token cũ và nhận `401 SIGNATURE_INVALID` ở `/v1/relay` và ở các lệnh REST cho tới khi token hết hạn (tối đa 15 phút). Cặp ghép nối trong khoảng đó bị từ chối với 401 và phải chờ 24 giờ (trong bộ nhớ) rồi ứng dụng mới đăng ký lại. Hãy khởi động lại ứng dụng (cài lại APK) sau khi khởi động lại relay.

## Những gì không chứng minh được

- Apple và Google có giao push hay không: token thật, APNs và FCM chấp nhận, thông báo hiện trên máy. Máy chủ giả chỉ kiểm những gì relay gửi đi, không kiểm nhà cung cấp làm gì với nó.
- Đường TLS thật: chứng chỉ Let's Encrypt trên VPS và pin ISRG Root X1/X2. Ứng dụng được thử bằng bản debug đã vá; bản release giữ nguyên cách tin CA hệ thống.
- FCM đánh thức ứng dụng thật: flavor `foss` không có Firebase nên không đăng ký push token. Wake chỉ được kiểm bằng thiết bị giả.
- Nhiều instance relay, reverse proxy thật, mạng di động và thời gian chờ NAT.

## Các tệp

| Tệp | Công dụng |
|-----|-----------|
| `relay_stack.py` | `up`, `down`, `status`, `check`, `captures` |
| `stack_config.py`, `stack_processes.py` | Cổng, bố cục thư mục trạng thái, `relay_stack.json`; tiến trình, PostgreSQL, Redis |
| `local_keys.py` | CA thử và chứng chỉ máy chủ, SPKI pin, khóa APNs, service account FCM |
| `tls_front.py` | TLS front có `X-Forwarded-For` |
| `mock_apns.py`, `mock_fcm.py`, `jwt_verify.py`, `capture_log.py` | Nhà cung cấp push giả, kiểm token, tệp capture |
| `stack_rest.py`, `push_crypto.py` | Thiết bị giả (HLREG1, HLAUTH1, cặp); envelope push niêm phong và mở bằng `K_push` |
| `stack_checks.py`, `push_checks.py`, `check_report.py` | Các kiểm tra |
| `build_android_for_local_relay.sh`, `android_patches/` | Build Android cho relay cục bộ; hai bản vá đề xuất chỉ dành cho bản debug |
| `self_test.py` | Các thành phần, không cần dịch vụ (CI) |
| `requirements.txt` | Ghim phiên bản: phụ thuộc của bài thử tải, thêm `h2`, `hpack`, `hyperframe` (MIT) |
