[English](README.md) | Tiếng Việt

# Đo hiệu năng: độ trễ bảng nhớ tạm và thời gian kết nối lại

Các script này đo các mục tiêu Phase 1 của cổng G1 từ log có dấu thời gian của cả hai thiết bị:

| Chỉ số | Mục tiêu | Tính từ → tới |
|--------|----------|---------------|
| Clip văn bản (gửi thẳng trong envelope) | < 50 ms | bên gửi có nội dung (`clip_read`) → bên nhận ghi xong bảng nhớ tạm (`clip_applied`); thời gian phát hiện sao chép báo riêng (04-clipboard QC9) |
| Ảnh khoảng 5 MB | < 2 s | như trên |
| Kết nối lại | < 3 s | mạng có lại hoặc Mac thức dậy (`net`, `wake`) → client về `Connected` (CONN-02, 00-common-specs 0.11) |

Đạt mục tiêu khi phân vị 95 nằm dưới mục tiêu. Python 3.10+, chỉ dùng thư viện chuẩn.

| File | Việc |
|------|------|
| `bench_log.py` | Đọc các dòng `HLBENCH/1` mô tả dưới đây |
| `clock_sync.py` | Độ lệch đồng hồ giữa hai thiết bị, tính từ các lượt yêu cầu/ack của chính chúng |
| `clip_latency.py` | Độ trễ bảng nhớ tạm theo từng lần truyền và theo nhóm kích thước |
| `reconnect_time.py` | Thời gian kết nối lại theo từng lần |
| `collect_logs.sh` | Ghi một phiên đo: Android qua `adb logcat`, Mac qua `log stream` |
| `make_test_png.py` | Tạo ảnh PNG không nén được với kích thước cho trước, dùng cho các kịch bản ảnh |
| `self_test.py` | Chạy các script trên log giả có thời gian biết trước (CI chạy) |

## Định dạng dòng log `HLBENCH/1`

Hai ứng dụng ghi mỗi sự kiện một dòng, **chỉ ở bản debug** (bản phát hành không bao giờ ghi):

- Android: `Log.i("HLBENCH", line)`.
- macOS: `Logger(subsystem: "app.handlive.mac", category: "bench").info("\(line, privacy: .public)")` — thiếu `.public` thì unified log che giá trị. iOS/iPadOS (Phase 2): subsystem `app.handlive.ios`.

```text
HLBENCH/1 wall=<ms> mono=<ns> dev=<id8> role=<android|macos|ios> ev=<event> [<key>=<value> ...]
```

| Trường | Giá trị |
|--------|---------|
| `wall` | Đồng hồ thực của thiết bị, ms kể từ Unix epoch, tối đa 3 chữ số thập phân (Android `System.currentTimeMillis()`; Apple `Date().timeIntervalSince1970 * 1000`) |
| `mono` | Đồng hồ đơn điệu vẫn đếm khi máy ngủ, ns (Android `SystemClock.elapsedRealtimeNanos()`; Apple `clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)`). Không bắt buộc nhưng nên có: khoảng thời gian trên một thiết bị dùng nó |
| `dev` | 8 chữ số hex đầu của `device_id` của thiết bị |
| `role` | `android`, `macos` hoặc `ios` |
| `ev` | Một trong các sự kiện dưới |

Giá trị không chứa khoảng trắng. Mọi thứ trước dấu `HLBENCH/1 ` (tiền tố của logcat hay `log stream`) bị bỏ qua. Quyền riêng tư (QC2, 0.6.5): không bao giờ ghi nội dung bảng nhớ tạm, tên thiết bị, tên liên hệ hay địa chỉ — chỉ `clip_id` ngẫu nhiên, loại, kích thước và trạng thái.

| `ev` | Ai | Khi nào | Trường |
|------|----|---------|--------|
| `copy_detected` | Bên gửi | Thấy tín hiệu sao chép, trước khi đọc: sự kiện sao chép của Hỗ trợ tiếp cận hoặc `OnPrimaryClipChangedListener` trên Android; lượt hỏi vòng thấy `changeCount` đổi trên Mac | — |
| `clip_read` | Bên gửi | Nội dung đã nằm trong bộ nhớ, sẵn sàng mã hóa (đã đọc văn bản, đã chuẩn hóa ảnh) — **điểm bắt đầu của độ trễ** | `clip`, `kind` (`text`, `image`), `bytes` (số byte UTF-8 của văn bản, số byte của ảnh đã chuẩn hóa), `source` (`auto`, `manual`, `share`, `mac`) |
| `clip_sent` | Bên gửi | Đã đưa `clipboard/push` cho WebSocket, mỗi đối phương một dòng (cả khi điện thoại chuyển tiếp clip, QC6) | `clip`, `peer` |
| `clip_received` | Bên nhận | Đã giải mã `clipboard/push` | `clip`, `peer` (thiết bị gửi tới), `kind`, `bytes` |
| `clip_applied` | Bên nhận | Lệnh ghi bảng nhớ tạm hệ thống đã trả về; với nội dung theo chunk là sau khi kiểm xong khối cuối — **điểm kết thúc của độ trễ** | `clip` |
| `ack_sent` | Bên nhận | Đã đưa `ack` của push đó cho WebSocket | `clip`, `peer`, `status` (`applied`, `ignored`, `rejected`) |
| `ack_received` | Bên gửi | Đã giải mã `ack` đó | `clip`, `peer`, `status` |
| `state` | Mac, iPhone, iPad | Mỗi lần chuyển trạng thái của máy trạng thái 0.11 | `to` (`Idle`, `Discovering`, `ConnectingLAN`, `ConnectingRelay`, `Handshaking`, `WaitingPeer`, `Connected`, `Backoff`); `from` không bắt buộc; `channel` (`lan`, `relay`, `usb`) đi cùng `Connected` |
| `net` | Mọi thiết bị | Hệ điều hành báo mạng đổi: Android `ConnectivityManager.NetworkCallback`, Apple `NWPathMonitor` | `change`: `up` (có mạng), `down` (mất mạng), `changed` (đổi mạng mặc định) |
| `wake` | Mac | `NSWorkspace.didWakeNotification` | — |

```text
HLBENCH/1 wall=1727151101000.000 mono=9001000000000 dev=8c7d6e5f role=android ev=clip_read clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e kind=text bytes=27 source=auto
HLBENCH/1 wall=1727151099770.500 mono=5001004000000 dev=5b1f8c2e role=macos ev=clip_received clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e peer=8c7d6e5f kind=text bytes=27
HLBENCH/1 wall=1727151142000.000 mono=5042000000000 dev=5b1f8c2e role=macos ev=state from=Discovering to=Connected channel=lan
```

## Đồng hồ

Đồng hồ của hai thiết bị có thể lệch nhau tới vài giây, lớn hơn nhiều so với 50 ms. Mỗi `clipboard/push` đều có `ack` và hai bên ghi đủ bốn thời điểm, nên `clock_sync.py` tính độ lệch như NTP (RFC 5905 §8): `offset = ((t2 − t1) + (t3 − t4)) / 2`, sai số không quá nửa thời gian khứ hồi của mạng. Với mỗi phép đo, script chọn lượt trao đổi có thời gian khứ hồi nhỏ nhất trong ±120 s (`--window-s`), nên đồng hồ trôi chậm trong phiên không ảnh hưởng; thiết bị cách hai chặng (iPad nhận clip qua điện thoại) được nối qua điện thoại. Phiên không có clip nào (ví dụ chỉ bật tắt Wi-Fi trên điện thoại) thì không có lượt trao đổi: sao chép một đoạn văn bản ngắn mỗi chiều lúc bắt đầu, hoặc truyền `--offset A:B=MS` (đồng hồ B trừ đồng hồ A); không thì độ lệch được coi là 0 và báo cáo ghi rõ. Dù sao vẫn bật giờ tự động theo mạng trên mọi thiết bị.

## Chạy

```sh
tools/bench/collect_logs.sh bench-logs/pixel8-mbp [adb-serial]   # ghi, Ctrl-C để dừng
python3 tools/bench/clip_latency.py bench-logs/pixel8-mbp/*.log   # thêm --json cho báo cáo, --check để thoát 1 khi không đạt
python3 tools/bench/reconnect_time.py bench-logs/pixel8-mbp/*.log
python3 tools/bench/make_test_png.py 5000000 image-5mb.png         # ảnh thử khoảng 5 MB
python3 tools/bench/self_test.py                                   # phải in "0 failed"
```

`clip_latency.py` in mỗi lần truyền một dòng (độ trễ, thời gian phát hiện sao chép, và phần của bên gửi, mạng, bên nhận), các clip đã đọc mà không bên nào ghi (bị từ chối vì xung đột, bị mất, hoặc thiếu log của máy kia), và bảng tóm tắt theo nhóm: văn bản gửi thẳng (≤ 180 KiB, mục tiêu 50 ms), văn bản theo chunk, ảnh dưới 4,5 MB, khoảng 5 MB (4,5–5,5 MB, mục tiêu 2 s) và lớn hơn. `reconnect_time.py` in mỗi lần kết nối lại một dòng kèm nguyên nhân (`net up on <dev>`, `wake on <dev>`, hoặc `loss` khi mạng không đổi gì) và kết quả so với mục tiêu.

## Kiểm thử tay theo ma trận thiết bị

Thiết bị (kế hoạch triển khai §5): Android — Pixel 8 (Android 14 hoặc 15), Galaxy S22/S23 (Android 14), Xiaomi hoặc OPPO (Android 13); Mac — Apple silicon chạy macOS 26, Intel chạy macOS 13 hoặc 14. Cổng G1 cần ít nhất Pixel, Samsung và một Mac; có đủ máy thì chạy mỗi điện thoại với cả hai Mac.

Chuẩn bị, một lần cho mỗi cặp:

1. Cài bản debug có bật log đo trên cả hai máy; ghép nối (PAIR-01); cùng một mạng Wi-Fi 5 GHz, bật giờ tự động theo mạng.
2. Android: bật tự gửi qua Hỗ trợ tiếp cận (CLIP-01), đã miễn tối ưu pin (SET-01). Mac: cắm sạc, cho phép "Dán từ ứng dụng khác" trên macOS 15.4+.
3. Ghi lại model điện thoại, phiên bản Android, model Mac, phiên bản macOS và số bản dựng của hai ứng dụng.
4. Chạy `tools/bench/collect_logs.sh bench-logs/<điện thoại>-<mac>` và để chạy suốt cả cặp.

Kịch bản (nghỉ 3 s giữa các lần lặp):

| # | Kịch bản | Lặp |
|---|----------|-----|
| T1 | Điện thoại → Mac, tự gửi: sao chép đoạn văn bản 20–100 ký tự trong Chrome, dán trên Mac | 20 |
| T2 | Mac → điện thoại: sao chép đoạn văn bản 20–100 ký tự trong TextEdit, dán trên điện thoại | 20 |
| T3 | Điện thoại → Mac, thủ công: sao chép rồi chạm "Gửi bảng nhớ tạm" trên thông báo (và một lần bằng ô Cài đặt nhanh) | 5 |
| T4 | Văn bản khoảng 200 KiB (theo chunk) mỗi chiều — ghi lại, không có mục tiêu | 1 + 1 |
| I1 | Ảnh 5 MB (`make_test_png.py 5000000`), điện thoại → Mac và Mac → điện thoại: mở ảnh, sao chép, dán | 5 + 5 |
| I2 | Ảnh 1 MB và 10 MB mỗi chiều; ảnh 11 MB phải bị từ chối với "Ảnh quá lớn (tối đa 10 MB)" | mỗi loại 1 |
| R1 | Tắt Wi-Fi trên Mac, chờ 5 s, bật lại | 5 |
| R2 | Mac chuyển giữa hai SSID của cùng một mạng LAN (ví dụ băng 2,4 và 5 GHz của một router) | 5 |
| R3 | Tắt Wi-Fi trên điện thoại, chờ 5 s, bật lại (trước đó sao chép mỗi chiều một đoạn văn bản để có độ lệch đồng hồ) | 5 |
| R4 | Mac ngủ (gập máy 30 s) rồi thức | 3 |
| R5 | Tắt màn hình điện thoại 5 phút (Doze), rồi sao chép trên Mac — phải tới nơi; ghi lại, không có mục tiêu | 2 |

Sau đó dừng ghi, chạy hai script và điền một dòng cho mỗi cặp (phân vị 95, đơn vị ms; đính kèm đầu ra `--json` vào báo cáo):

| Điện thoại (Android) | Mac (macOS) | Văn bản điện thoại → Mac | Văn bản Mac → điện thoại | Ảnh 5 MB điện thoại → Mac | Ảnh 5 MB Mac → điện thoại | Kết nối lại (R1–R4) | Không được ghi | Ghi chú |
|----------------------|-------------|--------------------------|--------------------------|---------------------------|---------------------------|---------------------|----------------|---------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

Một cặp đạt khi mọi phân vị 95 dưới mục tiêu của nó và mục "Không được ghi" chỉ có những clip mà kịch bản chờ bị từ chối. Ghi các máy chặn dịch vụ Hỗ trợ tiếp cận hoặc `ClipboardReadActivity` vào `docs/deployment-guide.md` (rủi ro của phase 1).
