[English](README.md) | Tiếng Việt

# Bộ kiểm thử đầu cuối: app Android thật với một Mac giả

Bộ kiểm thử chạy app Android trên máy ảo, không chỉ bằng unit test. Một "Mac giả" viết bằng Python nói chuyện với app thật đúng như app Mac: ghép nối bằng PIN, kết nối TLS có ghim chứng chỉ, bắt tay phiên, trao đổi capability và mọi envelope mã hóa. adb điều khiển điện thoại: chạm qua giao diện, gọi đến từ modem của máy ảo và gửi SMS vào máy. Mỗi bước in PASS hoặc FAIL kèm độ trễ và mục spec được kiểm.

Máy build không có Xcode, nên app Mac và app iPhone không chạy được ở đây. Mac giả đứng thay chúng.

## Phạm vi kiểm

| Kịch bản | Nội dung kiểm | Spec |
|----------|---------------|------|
| `setup` | Cài APK. Lần chạy đầu qua giao diện: màn chào, lời giải thích và hộp thoại thông báo, dịch vụ `connectedDevice`, miễn tối ưu pin. Ghép nối bằng PIN: nhập sai PIN và "2 attempts left", Mac kết nối trước khi PIN được nhập, Mã an toàn giống nhau hai bên. Phiên đầu: thời gian bắt tay, capability của điện thoại, "Connected to …", mỗi cặp một phiên (4409), `PAIR_UNKNOWN`, 4408, 4411 | SET-01 A, PAIR-01 A1–A5, PAIR-02, CONN-01, CONN-02 |
| `clipboard` | Văn bản Mac → điện thoại, push trùng và gửi lại, văn bản chia khối, ảnh PNG 300 kB và 5 MB, `CLIP_TOO_LARGE`, `CLIP_CHECKSUM_MISMATCH`. Điện thoại → Mac không cần Trợ năng: nút Send Clipboard (cũng chứng minh văn bản của Mac đã vào clipboard điện thoại) và Share target | CLIP-01…03 |
| `sms` | Cấp quyền và bản cập nhật capability. `sms/new` từ modem. Đồng bộ lần đầu chia trang quá 180 KiB, đồng bộ bù, lỗi cursor. Chia trang `sms/history`. `sms/send` với `sms/status` chỉ tiến, dòng Sent có `local_id`, chống gửi trùng, các lỗi gửi. `sms/read_changed`. Thu hồi `READ_SMS` và thông báo gợi ý cấp quyền | SMS-01…05, SET-01 B |
| `calls` | Cuộc gọi đến kèm tên danh bạ giả. Nghe, từ chối, kết thúc từ Mac, đối chiếu trạng thái cuộc gọi của chính Android. `CALL_HFP_REQUIRED`, `CALL_ACTION_NOT_ALLOWED`, `CALL_NOT_FOUND`. Kết nối lại giữa cuộc gọi. Cuộc gọi chờ khi modem tạo được. `log_new` cho cuộc đã nghe, đã từ chối, gọi nhỡ. Chia trang `log_sync` và cursor hỏng. Sau đó chạy `tools/bench/call_latency.py` trên lượt chạy | CALL-01…04 |
| `all` | `setup clipboard sms calls` theo thứ tự đó | |
| `relay` | Cần bộ relay cục bộ (`relay_stack/`) và app build cho nó. Một Mac giả thứ hai đăng ký với relay trước khi ghép nối; điện thoại đăng ký cặp. Mạng LAN mất đi (gỡ forward, bỏ phiên không gửi `session/bye`); điện thoại phải lên `/v1/relay`. Sau đó qua relay: bắt tay phiên, cuộc gọi đến, nghe và kết thúc, SMS mới, `sms/sync` và một tin trả lời | CONN-03, PAIR-01 API 8, PAIR-02 API 1 |
| `push` | Cùng bộ relay. Một iPhone giả đăng ký token APNs, ghép nối, chào tạm biệt rồi tắt. SMS đến và cuộc gọi đến phải tới APNs giả (`sms_new`, `call_incoming`); `hl` mở được bằng `K_push` của cặp. Sau đó iPhone từ chối cuộc gọi qua relay; cuộc gọi thứ hai người gọi bỏ máy thì gửi `call_missed` cùng collapse id | CONN-04, SMS-02 bước 10, CALL-01 bước 5, CALL-02 B1–B3, CALL-04 API 5 |

Mọi tin gửi và nhận đều được kiểm theo `shared/schemas`. Phần mật mã lấy từ `tools/vectors`, chính mã sinh test vector.

## Những gì không kiểm được

- Mac, iPhone, iPad thật: giao diện, thông báo, Keychain, `NSPasteboard`, HFP. Mac giả chỉ làm phần giao thức cần.
- Tìm máy qua mDNS: mạng máy ảo không truyền multicast. Client gọi thẳng cổng đã forward, như đường tắt `last_host` của Mac.
- Dịch vụ push của Apple và Google: kịch bản `push` dừng ở APNs giả của `relay_stack/`. Giai đoạn relay còn cần app build cho relay cục bộ với hai bản vá debug của `relay_stack/`.
- Tự gửi clipboard qua dịch vụ Trợ năng.
- Cuộc gọi chờ trên Android 11 trở lên: modem giả lập của máy ảo không tạo cuộc thứ hai khi đang có cuộc gọi.
- Thời gian trên máy thật. Máy ảo trên một máy chủ bận không phải điện thoại; độ trễ chỉ cho thấy xu hướng, không thay chỉ tiêu của cổng G1.

## Cách chạy

```sh
# một lần: venv và APK debug (build từ kho android)
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/e2e/requirements.txt
(cd ../android && ./gradlew :app:assembleFossDebug)

# máy ảo có cửa sổ, để xem từng bước
$ANDROID_HOME/emulator/emulator -avd hl-e2e-api35 -no-audio -gpu host -no-snapshot -port 5556 &

tools/.venv/bin/python tools/e2e/e2e.py all --serial emulator-5556 \
    --apk ../android/app/build/outputs/apk/foss/debug/app-foss-debug.apk
tools/.venv/bin/python tools/e2e/e2e.py calls --serial emulator-5556 --step-delay 0   # chạy nhanh, dùng lại cặp
```

| Tùy chọn | Mặc định | Dùng để |
|----------|----------|---------|
| `--serial` | `emulator-5556` | Máy ảo; mọi lệnh adb đều kèm `-s` |
| `--apk` | không có | Cài lại app ở `setup` và ghép nối lại; không có thì `setup` giữ app và cặp cũ |
| `--state-dir` | `$HL_E2E_STATE_DIR` hoặc `<tmp>/handlive-e2e/<serial>` | Trạng thái cặp, log và kết quả. Thư mục chứa khóa thử nghiệm: để ngoài kho mã |
| `--host-port` | 47800 + cổng − 5500 | Đầu phía máy chủ của `adb forward` tới cổng 47800 của điện thoại |
| `--step-delay` | 1 s | Nghỉ sau mỗi thao tác thấy được; 0 để chạy nhanh |
| `--shared-device` | tắt | Máy ảo dùng chung với client khác: không cho `--apk` và bỏ qua bước thu hồi quyền (bước này khởi động lại app) |
| `--lock-dir` | thư mục `.locks` của workspace | Mỗi kịch bản giữ khóa `<lock-dir>/<serial>` (chờ nếu đang bị giữ; khóa quá 30 phút coi là cũ) |
| `--relay-state` | `$HANDLIVE_RELAY_STACK_DIR` hoặc `<tmp>/handlive-relay-stack` | Thư mục trạng thái của `relay_stack.py up` (cho `relay` và `push`) |

Lượt chạy in một dòng cho mỗi bước và một bảng tổng. Có bước FAIL thì thoát với mã 1. Thư mục trạng thái giữ:

- `results.json`: mọi bước kèm trạng thái, chi tiết và độ trễ;
- `hlbench-mac.log` và `logcat-hlbench.log`: các dòng `HLBENCH/1` của Mac giả (`role=macos`) và của điện thoại, cho `tools/bench/*.py`;
- `call_latency.txt`: báo cáo của `tools/bench/call_latency.py`;
- `pair-macos.json`: khóa và cặp của Mac giả (quyền 0600).

Số điện thoại và tên đều là giả: số 555-01xx mã vùng 201 (libphonenumber chấp nhận) và danh bạ "E2E Test Contact". Các hội thoại SMS gieo sẵn bị xóa và ghi lại khi không khớp.

## Các file

| File | Vai trò |
|------|---------|
| `e2e.py` | Lệnh chạy: tham số, máy ảo, các kịch bản theo thứ tự |
| `fake_mac.py` | Mac giả: danh tính, capability, ghép nối và phiên |
| `mac_crypto.py` | Khóa, ghép nối PIN, khóa phiên, envelope, khối (từ `tools/vectors`) |
| `mac_pairing.py`, `mac_session.py` | `/v1/pair` bằng PIN; `/v1/ctl` với ack, sự kiện và kiểm schema |
| `transport.py` | TLS 1.3 có ghim chứng chỉ, WebSocket ping mỗi 15 s |
| `pair_store.py`, `schema_check.py`, `bench_lines.py` | File cặp, kiểm schema, dòng `HLBENCH/1` |
| `adb_device.py`, `ui_automator.py` | adb, console máy ảo, các provider; đọc màn hình bằng `uiautomator` với chữ lấy từ catalog chuỗi |
| `relay_client.py` | Client trên bộ relay: đăng ký, JWT, cặp, token APNs, `/v1/relay`, kênh relay cho phiên |
| `scenario_*.py`, `steps.py` | Các kịch bản (`scenario_common.py`: quyền và số điện thoại giả) và dòng PASS/FAIL |
| `self_test.py`, `fake_phone.py` | Tự kiểm (CI): mật mã so với vector, cả client với một điện thoại giả chạy trong tiến trình, rồi cùng phiên đó qua relay giả của `tools/bench` |

```sh
tools/.venv/bin/python tools/e2e/self_test.py      # phải in "0 failed"
```
