[English](README.md) | Tiếng Việt

# Đo hiệu năng: bảng nhớ tạm, SMS, cuộc gọi, kết nối lại và tải của relay

Các script này đo các mục tiêu Phase 1 của cổng G1, các mục tiêu Phase 2 và Phase 3 từ log có dấu thời gian của các thiết bị, và thử tải relay:

| Chỉ số | Mục tiêu | Tính từ → tới |
|--------|----------|---------------|
| Clip văn bản (gửi thẳng trong envelope) | < 50 ms | bên gửi có nội dung (`clip_read`) → bên nhận ghi xong bảng nhớ tạm (`clip_applied`); thời gian phát hiện sao chép báo riêng (04-clipboard QC9) |
| Ảnh khoảng 5 MB | < 2 s | như trên |
| Kết nối lại | < 3 s | mạng có lại hoặc Mac thức dậy (`net`, `wake`) → client về `Connected` (CONN-02, 00-common-specs 0.11) |
| Thông báo SMS mới trên Mac (Phase 2) | < 500 ms trong LAN, ≤ 1 s qua relay | `ContentObserver` của điện thoại được gọi (`sms_detected` trường `onchange`) → client đăng thông báo (`sms_notified`) (SMS-02) |
| Trả lời được xác nhận Đã gửi (Phase 2) | < 2 s | người dùng bấm Gửi (`sms_send_tap`) → client hiện Đã gửi (`sms_status_received status=sent`), trên cùng một máy (SMS-04); kèm bong bóng tạm < 100 ms và ack < 300 ms trong LAN |
| Trạng thái cuộc gọi trên client (Phase 3) | < 200 ms trong LAN, ≤ 1 s qua relay | callback hoặc broadcast của hệ điều hành gây ra thay đổi trên điện thoại (`call_changed` trường `os`) → client giải mã được `call_event/state` mang thay đổi đó (`call_state_received`, ghép theo id envelope) (CALL-01) |
| Hiện cuộc gọi (Phase 3) | ≤ 300 ms | callback RINGING đầu tiên → panel trên Mac (`call_panel_shown`) hoặc banner trong ứng dụng trên iPhone/iPad (`call_banner_shown`) (CALL-01) |
| Trả lời từ Mac (Phase 3) | < 500 ms đầu-cuối | bấm Trả lời (`call_action_tap action=answer`) → callback OFFHOOK của điện thoại, và → Mac nhận `state = offhook`; Từ chối và Kết thúc → client nhận `state = idle`, cũng < 500 ms (CALL-02, CALL-03) |
| Từ chối từ thông báo iPhone/iPad (Phase 3) | < 2 s qua relay | `call_action_tap from=notification` → callback IDLE của điện thoại (CALL-02 B1–B3) |
| Thông báo cuộc gọi nhỡ (Phase 3) | ≤ 1,5 s | callback IDLE của một cuộc gọi nhỡ trên điện thoại → `call_missed_notified` (CALL-04) |
| Push cuộc gọi đến (Phase 3) | < 300 ms sau khi số đã rõ | `call_changed settled=true` đầu tiên của cuộc gọi — broadcast mang số, bản đổ chuông thứ hai không có số khi người gọi ẩn số, hoặc chính `RINGING` khi thiếu `READ_CALL_LOG` — hoặc `RINGING` + 300 ms khi trong lúc chờ đó số chưa rõ → `call_push_sent status=202`, chỉ trên điện thoại (CALL-01 API 4 logic 2); thời gian phần mở rộng hiện thông báo (`call_push_shown`) không có mục tiêu |
| Relay với 1 000 kết nối (Phase 2) | không lỗi, không mất khung | `relay_load.py`: đăng ký, ghép cặp, `/v1/relay`, các phân vị độ trễ chuyển tiếp |

Đạt mục tiêu khi phân vị 95 nằm dưới mục tiêu. Python 3.10+, chỉ dùng thư viện chuẩn — trừ phép thử tải relay, cần `requirements-load.txt`.

| File | Việc |
|------|------|
| `bench_log.py` | Đọc các dòng `HLBENCH/1` mô tả dưới đây |
| `clock_sync.py` | Độ lệch đồng hồ giữa hai thiết bị, tính từ các lượt yêu cầu/ack của chính chúng |
| `clip_latency.py` | Độ trễ bảng nhớ tạm theo từng lần truyền và theo nhóm kích thước |
| `reconnect_time.py` | Thời gian kết nối lại theo từng lần |
| `sms_latency.py` | Độ trễ thông báo SMS mới theo từng tin và theo nhóm (LAN, relay), thời gian từ bấm Gửi tới Đã gửi của từng lần gửi, thời gian bong bóng tạm và ack, thời gian hiện push |
| `call_latency.py` | Độ trễ trạng thái cuộc gọi theo từng envelope (LAN, relay), thời gian hiện panel và banner, thời gian trả lời, từ chối, kết thúc, từ chối từ thông báo iPhone/iPad, thông báo cuộc gọi nhỡ, thời gian push, và quy tắc Tập trung của cách báo trên Mac |
| `relay_load.py` | Thử tải relay: N thiết bị giả đi qua CONN-03 và `/v1/relay` (xem "Thử tải relay") |
| `relay_load_fake.py`, `relay_load_self_test.py` | Relay giả chạy trong tiến trình và bài kiểm `relay_load.py` với nó (CI) |
| `requirements-load.txt` | Phụ thuộc ghim phiên bản của phép thử tải: `cryptography` và PyNaCl của công cụ vector, `websockets` (BSD-3-Clause) |
| `collect_logs.sh` | Ghi một phiên đo: Android qua `adb logcat`, Mac qua `log stream` |
| `make_test_png.py` | Tạo ảnh PNG không nén được với kích thước cho trước, dùng cho các kịch bản ảnh |
| `self_test.py`, `sms_self_test.py`, `call_self_test.py` | Chạy các script trên log giả có thời gian biết trước (CI chạy) |

## Định dạng dòng log `HLBENCH/1`

Hai ứng dụng ghi mỗi sự kiện một dòng, **chỉ ở bản debug** (bản phát hành không bao giờ ghi):

- Android: `Log.i("HLBENCH", line)`.
- macOS: `Logger(subsystem: "app.handlive.mac", category: "bench").info("\(line, privacy: .public)")` — thiếu `.public` thì unified log che giá trị. iOS/iPadOS (Phase 2): subsystem `app.handlive.ios`; phần mở rộng dịch vụ thông báo `app.handlive.ios.nse`.

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
| `clip_read_failed` | Bên gửi (Android) | Không đọc được item ảnh nên không gửi gì (CLIP-03 E2, E3, E10) | `reason` (`image_too_large`, `image_unreadable`, `permission_lost`), `stage` (`copy`, `normalize`), `authority` của URI item (không bao giờ là đường dẫn), `source` |
| `clip_sent` | Bên gửi | Đã đưa `clipboard/push` cho WebSocket, mỗi đối phương một dòng (cả khi điện thoại chuyển tiếp clip, QC6) | `clip`, `peer` |
| `clip_received` | Bên nhận | Đã giải mã `clipboard/push` | `clip`, `peer` (thiết bị gửi tới), `kind`, `bytes` |
| `clip_applied` | Bên nhận | Lệnh ghi bảng nhớ tạm hệ thống đã trả về; với nội dung theo chunk là sau khi kiểm xong khối cuối — **điểm kết thúc của độ trễ** | `clip` |
| `ack_sent` | Bên nhận | Đã đưa `ack` của push đó cho WebSocket | `clip`, `peer`, `status` (`applied`, `ignored`, `rejected`) |
| `ack_received` | Bên gửi | Đã giải mã `ack` đó | `clip`, `peer`, `status` |
| `state` | Mac, iPhone, iPad | Mỗi lần chuyển trạng thái của máy trạng thái 0.11 | `to` (`Idle`, `Discovering`, `ConnectingLAN`, `ConnectingRelay`, `Handshaking`, `WaitingPeer`, `Connected`, `Backoff`); `from` không bắt buộc; `channel` (`lan`, `relay`, `usb`) đi cùng `Connected` |
| `net` | Mọi thiết bị | Hệ điều hành báo mạng đổi: Android `ConnectivityManager.NetworkCallback`, Apple `NWPathMonitor` | `change`: `up` (có mạng), `down` (mất mạng), `changed` (đổi mạng mặc định) |
| `wake` | Mac | `NSWorkspace.didWakeNotification` | — |

### Sự kiện SMS (Phase 2)

Quyền riêng tư như trên: chỉ `message_key` của provider (`sms:<_id>`), `local_id` ngẫu nhiên, trạng thái và mã lỗi — không bao giờ có nội dung tin, số điện thoại hay tên.

| `ev` | Ai | Khi nào | Trường |
|------|----|---------|--------|
| `sms_detected` | Điện thoại | A-SMS đọc được dòng mới sẽ phát đi (SMS-02 bước 3–4) | `msg` (`message_key`), `box` (`inbox`, `sent`, `failed`), `onchange` (đồng hồ thực, ms, của lần gọi `ContentObserver.onChange` đầu tiên trong đợt gộp — **điểm bắt đầu độ trễ thông báo**); không bắt buộc `provider` (cột `date` của dòng, ms) |
| `sms_new_sent` | Điện thoại | Đã giao `sms/new` cho phiên của một client | `msg`, `peer`, `via` (`lan`, `relay`) |
| `sms_new_received` | Mac, iPhone, iPad | Đã giải mã `sms/new` | `msg`, `peer` |
| `sms_notified` | Mac, iPhone, iPad | `UNUserNotificationCenter.add` xong không lỗi — **điểm kết thúc độ trễ thông báo**; không ghi khi không cần thông báo (SMS-02 bước 7) | `msg` |
| `sms_push_sent` | Điện thoại | `POST /v1/push` trả 202 cho iPhone/iPad không có phiên | `msg`, `peer` |
| `sms_push_shown` | iPhone, iPad (phần mở rộng) | Phần mở rộng giải mã push và gọi content handler | `msg` |
| `sms_send_tap` | Mac, iPhone, iPad | Bấm Gửi trong hội thoại hoặc Tin nhắn mới, hoặc gửi trả lời nhanh — **điểm bắt đầu thời gian trả lời** | `local` (`local_id`) |
| `sms_bubble` | Mac, iPhone, iPad | Bong bóng tạm đã hiện | `local` |
| `sms_send_sent` | Mac, iPhone, iPad | Đã giao `sms/send` cho WebSocket, mỗi lần thử một dòng | `local`, `peer`, `attempt` (1, 2…), `via` (`lan`, `relay`) |
| `sms_send_received` | Điện thoại | Đã giải mã `sms/send` | `local`, `peer` |
| `sms_send_ack_sent` | Điện thoại | Đã giao `ack` của nó cho WebSocket | `local`, `peer`, `ok` (`true`, `false`); không bắt buộc `code` (mã lỗi) |
| `sms_send_ack_received` | Mac, iPhone, iPad | Đã giải mã `ack` đó | `local`, `peer`, `ok`; không bắt buộc `code` |
| `sms_radio_done` | Điện thoại | Mọi phần đã có kết quả từ `SmsManager` (sent intent) | `local`, `result` (`sent`, `failed`); không bắt buộc `code` |
| `sms_status_sent` | Điện thoại | Đã giao `sms/status` cho WebSocket | `local`, `peer`, `status` (`sending`, `sent`, `delivered`, `failed`); không bắt buộc `code` |
| `sms_status_received` | Mac, iPhone, iPad | Trạng thái đã áp vào hàng đợi gửi và hiện ra — **điểm kết thúc thời gian trả lời** khi `status=sent` | `local`, `status`; không bắt buộc `code` |

### Sự kiện cuộc gọi (Phase 3)

Quyền riêng tư như trên và như nhóm chức năng cuộc gọi yêu cầu: chỉ `call_id` và id envelope ngẫu nhiên, trạng thái, `sub_id` của SIM và mã lỗi — không bao giờ có số điện thoại, tên liên hệ, nhãn SIM hay phím DTMF.

| `ev` | Ai | Khi nào | Trường |
|------|----|---------|--------|
| `call_changed` | Điện thoại | A-CALL áp một sự kiện của hệ điều hành làm đổi ngữ cảnh cuộc gọi (CALL-01 API 1–3; CALL-04 API 3 cho lần hiệu chỉnh `end_reason`) | `call` (`call_id`), `state` (`ringing`, `offhook`, `idle`), `waiting` (`true`, `false`), `trigger` (`listener`: listener trạng thái, API 2; `broadcast`: bản `PHONE_STATE` có số, API 3; `calllog`: lần hiệu chỉnh), `os` (đồng hồ thực, ms, lúc hệ điều hành giao callback hoặc broadcast đó — **điểm bắt đầu độ trễ trạng thái, panel, trả lời và cuộc gọi nhỡ**); không bắt buộc `number` (`known`, `none`: sau thay đổi ngữ cảnh đã có số người gọi hay chưa), `settled` (`true` khi sự kiện này làm rõ số người gọi: broadcast mang số, bản đổ chuông thứ hai không có khóa số khi đã có `READ_CALL_LOG` — người gọi ẩn số, CALL-01 API 3 logic 3 — hoặc chính `RINGING` khi thiếu `READ_CALL_LOG`; **điểm bắt đầu thời gian push cuộc gọi đến**, CALL-01 API 4 logic 2), `sub` (`sub_id`), `end` (`end_reason` khi `idle`) |
| `call_state_sent` | Điện thoại | Đã giao `call_event/state` cho phiên của một client | `call`, `env` (`id` của envelope), `peer`, `via` (`lan`, `relay`), `state`, `reason` (`change`: ngữ cảnh vừa đổi; `session`: trạng thái hiện tại gửi cho phiên mới, CALL-01 E8, không đo) |
| `call_state_received` | Mac, iPhone, iPad | Đã giải mã `call_event/state` — **điểm kết thúc độ trễ trạng thái** | `call`, `env`, `peer`, `state`; không bắt buộc `waiting` |
| `call_alert` | Mac | M-APP quyết định cách báo một cuộc gọi đang đổ chuông (CALL-01 bước 7) | `call`, `focus` (`off`, `on`, `unknown`: chưa đọc được trạng thái Tập trung, `unavailable`: bản build này không xin được quyền, báo như `off`), `panel`, `ring` (`true`, `false`), `level` (`passive`, `time_sensitive`, `none`) |
| `call_panel_shown` | Mac | Panel cuộc gọi đang đổ chuông đã hiện (`orderFrontRegardless()` đã trả về) — **điểm kết thúc độ trễ panel** | `call` |
| `call_banner_shown` | iPhone, iPad | Banner trong ứng dụng của cuộc gọi đang đổ chuông đã hiện | `call` |
| `call_notified` | Mac | Đã thêm thông báo liên lạc của cuộc gọi đến | `call`, `level` (`passive`, `time_sensitive`) |
| `call_push_sent` | Điện thoại | `POST /v1/push` đã có phản hồi, cho iPhone/iPad không có phiên | `call`, `peer`, `reason` (`call_incoming`, `call_missed`), `status` (mã HTTP) |
| `call_push_shown` | iPhone, iPad (phần mở rộng) | Phần mở rộng giải mã push cuộc gọi và gọi content handler | `call`, `reason`, `late` (`true` khi quá 60 s sau `started_at`, CALL-01 E7) |
| `call_action_tap` | Mac, iPhone, iPad | Người dùng chọn Trả lời, Từ chối (cả Từ chối kèm tin nhắn…) hoặc Kết thúc, hoặc hành động thông báo `HL_CALL_REJECT` tới được ứng dụng iPhone/iPad — **điểm bắt đầu thời gian thao tác** | `call`, `action` (`answer`, `reject`, `end`), `from` (`panel`, `menu`, `notification`, `banner`) |
| `call_action_sent` | Mac, iPhone, iPad | Đã giao `call_event/action` cho WebSocket, mỗi lần thử một dòng (gửi lại giữ nguyên `id` envelope) | `call`, `env`, `peer`, `action`, `via`, `attempt` |
| `call_action_received` | Điện thoại | Đã giải mã `call_event/action` | `call`, `env`, `peer`, `action` |
| `call_action_ack_sent` | Điện thoại | Đã giao `ack` của nó cho WebSocket (khi hàm Telecom đã trả về, hoặc kèm lỗi) | `call`, `env`, `peer`, `ok`; không bắt buộc `code` |
| `call_action_ack_received` | Mac, iPhone, iPad | Đã giải mã `ack` đó | `call`, `env`, `peer`, `ok`; không bắt buộc `code` |
| `call_missed_notified` | Mac, iPhone, iPad | Đã thêm thông báo cuộc gọi nhỡ — **điểm kết thúc độ trễ cuộc gọi nhỡ** | `call` (`none` khi không ghép được ngữ cảnh cuộc gọi nào), `source` (`log_new`; `state` khi không có nhật ký, luồng A); không bắt buộc `entry` (`entry_id`) |
| `app_call_changed` | Điện thoại | A-CALL áp một sự kiện thông báo làm đổi ngữ cảnh cuộc gọi ứng dụng (CALL-05 API 1) — **điểm bắt đầu độ trễ panel cuộc gọi ứng dụng** | `call` (app `call_id`), `state` (`ringing`, `ongoing`, `ended`), `os` (đồng hồ thực, ms, lúc listener đã đăng hoặc gỡ thông báo); không bắt buộc `app` (tên gói, một định danh), `answer_mode` (`direct`, `tap`) |
| `app_call_sent` | Điện thoại | Đã giao `call_event/app_call` cho một phiên | `call`, `env`, `peer`, `via`, `state` |
| `app_call_received` | Mac | Đã giải mã `call_event/app_call` — **điểm kết thúc độ trễ panel cuộc gọi ứng dụng** | `call`, `env`, `peer`, `state` |
| `app_call_panel_shown` | Mac | Panel đến hoặc đang gọi của cuộc gọi ứng dụng đã hiện | `call` |
| `app_call_intent_sent` | Điện thoại | Đã gửi PendingIntent của ứng dụng (`pendingIntent.send` đã trả về) — **điểm bắt đầu thời gian thao tác cuộc gọi ứng dụng** | `call`, `action` (`answer`, `reject`, `end`), `mode` (`direct`: không giới hạn mở activity, hoặc `tap`: chỉ thông báo) |
| `app_call_changed` (lại) | Điện thoại | A-CALL áp thay đổi thông báo của ứng dụng sau khi gửi intent — **điểm kết thúc độ trễ thao tác cuộc gọi ứng dụng** | `call`, `state` (trạng thái mới: `ongoing` sau trả lời, `ended` sau từ chối hoặc kết thúc) |

### Các dòng độ trễ cuộc gọi ứng dụng (Phase 3, CALL-05)

Được thêm vào đầu ra `call_latency.py`:

- `app call shown` (app_call_panel_shown sau app_call_changed ringing): ≤ 400 ms
- `app call decline` (app_call_changed ended sau app_call_intent_sent reject): ≤ 500 ms
- `app call end` (app_call_changed ended sau app_call_intent_sent end): ≤ 500 ms
- `app call answer direct` (app_call_changed ongoing sau app_call_intent_sent answer, mode=direct): ≤ 1 s
- `app call answer tap` (app_call_intent_sent tap mode; thao tác hoàn thành khi người dùng chạm thông báo trên điện thoại, không đo trong đo lường)

```text
HLBENCH/1 wall=1727151101000.000 mono=9001000000000 dev=8c7d6e5f role=android ev=clip_read clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e kind=text bytes=27 source=auto
HLBENCH/1 wall=1727151099770.500 mono=5001004000000 dev=5b1f8c2e role=macos ev=clip_received clip=0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e peer=8c7d6e5f kind=text bytes=27
HLBENCH/1 wall=1727151142000.000 mono=5042000000000 dev=5b1f8c2e role=macos ev=state from=Discovering to=Connected channel=lan
HLBENCH/1 wall=1727150400164.500 mono=9001041000000 dev=8c7d6e5f role=android ev=call_changed call=0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90 state=ringing waiting=false trigger=broadcast os=1727150400163.000 number=known settled=true sub=1
```

## Đồng hồ

Đồng hồ của hai thiết bị có thể lệch nhau tới vài giây, lớn hơn nhiều so với 50 ms. Mỗi `clipboard/push`, `sms/send` và `call_event/action` đều có `ack` và hai bên ghi đủ bốn thời điểm (bỏ qua `sms/send` hoặc `call_event/action` đã phải gửi lại), nên `clock_sync.py` tính độ lệch như NTP (RFC 5905 §8): `offset = ((t2 − t1) + (t3 − t4)) / 2`, sai số không quá nửa thời gian khứ hồi của mạng. Với mỗi phép đo, script chọn lượt trao đổi có thời gian khứ hồi nhỏ nhất trong ±120 s (`--window-s`), nên đồng hồ trôi chậm trong phiên không ảnh hưởng; thiết bị cách hai chặng (iPad nhận clip qua điện thoại) được nối qua điện thoại. Phiên không có clip nào (ví dụ chỉ bật tắt Wi-Fi trên điện thoại) thì không có lượt trao đổi: sao chép một đoạn văn bản ngắn mỗi chiều lúc bắt đầu, hoặc truyền `--offset A:B=MS` (đồng hồ B trừ đồng hồ A); không thì độ lệch được coi là 0 và báo cáo ghi rõ. Phiên chỉ có cuộc gọi lấy độ lệch từ các thao tác cuộc gọi: lúc bắt đầu, từ chối một cuộc gọi thử từ Mac (và một từ iPhone). Dù sao vẫn bật giờ tự động theo mạng trên mọi thiết bị.

## Chạy

```sh
tools/bench/collect_logs.sh bench-logs/pixel8-mbp [adb-serial]   # ghi, Ctrl-C để dừng
python3 tools/bench/clip_latency.py bench-logs/pixel8-mbp/*.log   # thêm --json cho báo cáo, --check để thoát 1 khi không đạt
python3 tools/bench/reconnect_time.py bench-logs/pixel8-mbp/*.log
python3 tools/bench/sms_latency.py bench-logs/pixel8-mbp/*.log     # --json, --check như trên
python3 tools/bench/call_latency.py bench-logs/pixel8-mbp/*.log    # --json, --check như trên
python3 tools/bench/make_test_png.py 5000000 image-5mb.png         # ảnh thử khoảng 5 MB
python3 tools/bench/self_test.py                                   # phải in "0 failed"
```

`clip_latency.py` in mỗi lần truyền một dòng (độ trễ, thời gian phát hiện sao chép, và phần của bên gửi, mạng, bên nhận), các clip đã đọc mà không bên nào ghi (bị từ chối vì xung đột, bị mất, hoặc thiếu log của máy kia), và bảng tóm tắt theo nhóm: văn bản gửi thẳng (≤ 180 KiB, mục tiêu 50 ms), văn bản theo chunk, ảnh dưới 4,5 MB, khoảng 5 MB (4,5–5,5 MB, mục tiêu 2 s) và lớn hơn. `reconnect_time.py` in mỗi lần kết nối lại một dòng kèm nguyên nhân (`net up on <dev>`, `wake on <dev>`, hoặc `loss` khi mạng không đổi gì) và kết quả so với mục tiêu.

`sms_latency.py` in mỗi tin đã thông báo một dòng (độ trễ theo đồng hồ điện thoại và các phần: phát hiện, điện thoại, mạng, client), các tin đến đã gửi cho client mà không có thông báo (tắt cài đặt, đang mở hội thoại, bị mất), mỗi lần trả lời một dòng (số lần thử, trạng thái cuối, thời gian tới Đã gửi, bong bóng, ack, thời gian radio trên điện thoại, mã lỗi), thời gian hiện push, và bảng tóm tắt trung vị, phân vị 95, lớn nhất: `notification lan` (mục tiêu 500 ms), `notification relay` (1 s), `reply sent` (2 s), `placeholder bubble` (100 ms), `ack lan` (300 ms, chỉ lần gửi không phải thử lại), `push shown` (không có mục tiêu). Thời gian trả lời không cần độ lệch đồng hồ (một máy); độ trễ thông báo thì cần — gửi một tin trả lời lúc bắt đầu phiên, hoặc truyền `--offset`.

`call_latency.py` in mỗi envelope trạng thái một dòng (độ trễ theo đồng hồ điện thoại, nguồn gây thay đổi, và phần điện thoại, phần mạng), các envelope không tới client, thời gian hiện panel và banner, mỗi thao tác một dòng (nguồn, đường truyền, số lần thử, ack, bấm → callback của điện thoại, bấm → trạng thái kết quả trên client, thời gian ack, mã lỗi), các thông báo cuộc gọi nhỡ, các push (mã HTTP, thời gian sau khi có số, lúc phần mở rộng hiện), các lần báo trên Mac sai quy tắc Tập trung (Tập trung bật: không panel, không chuông, thông báo time-sensitive; không đọc được trạng thái Tập trung: có panel, không chuông; có panel thì thông báo luôn ở mức passive), và bảng tóm tắt: `state lan` (200 ms), `state relay` (1 s), `shown panel` và `shown banner` (300 ms), `answer to phone offhook`, `answer back on client`, `decline back on client`, `end back on client` (500 ms), `decline from notification` (2 s), `missed notification` (1,5 s), `incoming push` (300 ms), `push shown` (không có mục tiêu). `--check` cũng báo lỗi khi sai quy tắc Tập trung. Thời gian từ bấm tới trạng thái trên chính client không cần độ lệch đồng hồ; các thời gian còn lại thì cần.

## Thử tải relay

`relay_load.py` cho N thiết bị giả (mặc định 1 000) đi qua relay đúng như ứng dụng: `POST /v1/devices` (`HLREG1`), `POST /v1/auth/challenge` + `/v1/auth/token` (`HLAUTH1`) — thông điệp và chữ ký Ed25519 lấy từ `tools/vectors/handlive_protocol_derivations.py`, mã sinh ra `test-vectors/relay-auth.json` — rồi `POST /v1/pairs` cho thiết bị 2k (android) và 2k+1 (macos/ios) với attestation 0.6.2 do cả hai ký, và `/v1/relay`. Khi mọi thiết bị đã kết nối, mỗi thiết bị gửi `--frames` khung cho đối phương, mỗi `--interval-ms` một khung — lớp bọc văn bản, xen kẽ khung nhị phân `HR` khi có `--binary` — và phía nhận trong cùng tiến trình ghi thời điểm (một đồng hồ đơn điệu). Báo cáo liệt kê lỗi theo từng bước (mã HTTP và mã lỗi), op `error` của relay, WebSocket đóng bất thường, khung bị mất, và p50/p95/p99/lớn nhất của đăng ký, kết nối, chuyển tiếp; `--check` thoát 1 khi có bất kỳ mục nào; `--cleanup` xóa các thiết bị sau khi chạy (`DELETE /v1/devices/me?revoke_pairs=false`).

```sh
tools/.venv/bin/python -m pip install -r tools/bench/requirements-load.txt
RELAY_TRUSTED_PROXIES=127.0.0.1 …relay-server        # để X-Forwarded-For riêng của mỗi thiết bị được tính (10 lần đăng ký/giờ/IP)
tools/.venv/bin/python tools/bench/relay_load.py --relay http://127.0.0.1:8080 --devices 1000 --frames 10 --binary --cleanup --check
tools/.venv/bin/python tools/bench/relay_load_self_test.py   # với relay giả chạy trong tiến trình (CI)
```

Mỗi kết nối cần một file descriptor ở cả hai phía: chạy relay với `ulimit -n` vài nghìn (script tự nâng giới hạn của nó). Để kiểm kết nối rảnh vẫn sống qua ngưỡng rảnh 45 s của relay chỉ nhờ ping WebSocket, đặt các khung cách nhau hơn 45 s (`--frames 3 --interval-ms 50000`).

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
| S1 | Phase 2: nhắn SMS tới điện thoại từ một máy khác khi Mac không mở hội thoại nào (LAN) | 20 |
| S2 | Phase 2: như S1 khi Mac ở mạng khác (kết nối qua Internet, relay) | 10 |
| S3 | Phase 2: trả lời từ cửa sổ Tin nhắn của Mac khi sóng bình thường (mở đầu bằng một tin trả lời để có độ lệch đồng hồ) | 20 |
| S4 | Phase 2: trả lời nhanh từ thông báo trên Mac; rồi từ iPhone khi HandLive chạy nền | 5 + 5 |
| C1 | Phase 3: gọi từ một điện thoại khác, Mac trong LAN, không bật Tập trung: có panel và chuông; để đổ chuông 5 s rồi từ chối trên điện thoại (bắt đầu bằng một lần từ chối từ Mac để có độ lệch đồng hồ) | 20 |
| C2 | Phase 3: trả lời từ panel trên Mac (Return), nói 10 s trên điện thoại, kết thúc từ panel trên Mac | 10 |
| C3 | Phase 3: từ chối từ panel trên Mac (⌘⌫); hai lần dùng Từ chối kèm tin nhắn… với một mẫu tin | 10 + 2 |
| C4 | Phase 3: cuộc gọi chờ (CALL-01 E9): đang nói một cuộc gọi đã nghe trên điện thoại thì có cuộc gọi từ máy thứ ba: Mac chỉ hiện thông tin người gọi chờ, ẩn Kết thúc, không push cho iPhone; từ chối cuộc gọi chờ trên điện thoại | 3 |
| C5 | Phase 3: hai SIM: gọi tới từng SIM của một điện thoại hai SIM; panel và thông báo hiện đúng nhãn SIM (`sub` của `call_changed`) | 3 + 3 |
| C6 | Phase 3: bật Tập trung trên Mac: không panel, không chuông, thông báo time-sensitive, cuộc gọi vẫn ở menu của biểu tượng thanh menu; rồi khi chưa cấp quyền đọc trạng thái Tập trung: có panel, không chuông | 3 + 2 |
| C7 | Phase 3: AirPods đang nối với điện thoại: làm lại C1 và C2; âm thanh vẫn ở điện thoại hoặc AirPods (không ảnh hưởng ở phase này) | 3 |
| C8 | Phase 3: iPhone có HandLive chạy nền (không có phiên), điện thoại kết nối được qua relay: push cuộc gọi đến, rồi Từ chối từ thông báo (mở khóa) | 10 |
| C9 | Phase 3: cuộc gọi nhỡ (để đổ chuông hết) khi Mac đang kết nối; rồi khi iPhone chạy nền, push cuộc gọi nhỡ thay thế push cuộc gọi đến | 5 + 3 |
| C10 | Phase 3: iPhone đang mở HandLive: banner trong ứng dụng, Từ chối từ banner | 5 |

Sau đó dừng ghi, chạy hai script và điền một dòng cho mỗi cặp (phân vị 95, đơn vị ms; đính kèm đầu ra `--json` vào báo cáo):

| Điện thoại (Android) | Mac (macOS) | Văn bản điện thoại → Mac | Văn bản Mac → điện thoại | Ảnh 5 MB điện thoại → Mac | Ảnh 5 MB Mac → điện thoại | Kết nối lại (R1–R4) | Không được ghi | Ghi chú |
|----------------------|-------------|--------------------------|--------------------------|---------------------------|---------------------------|---------------------|----------------|---------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

Phase 2 thêm một dòng cho mỗi cặp từ `sms_latency.py` (phân vị 95, đơn vị ms):

| Điện thoại (Android) | Client | Thông báo LAN (S1) | Thông báo relay (S2) | Trả lời Đã gửi (S3) | Bong bóng | Ack LAN | Không thông báo | Ghi chú |
|----------------------|--------|--------------------|----------------------|---------------------|-----------|---------|-----------------|---------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | |

Phase 3 thêm một dòng cho mỗi cặp từ `call_latency.py` (phân vị 95, đơn vị ms):

| Điện thoại (Android) | Client | Trạng thái LAN (C1) | Panel (C1) | Trả lời → offhook (C2) | Trả lời về client (C2) | Từ chối về client (C3) | Kết thúc về client (C2) | Từ chối từ thông báo (C8) | Nhỡ (C9) | Push (C8) | Quy tắc Tập trung (C6) | Ghi chú |
|----------------------|--------|---------------------|------------|------------------------|------------------------|------------------------|-------------------------|---------------------------|----------|-----------|------------------------|---------|
| Pixel 8 (15) | MacBook Pro M3 (26) | | | | | | | | | | | |

Một cặp đạt khi mọi phân vị 95 dưới mục tiêu của nó và mục "Không được ghi" chỉ có những clip mà kịch bản chờ bị từ chối. Ghi các máy chặn dịch vụ Hỗ trợ tiếp cận hoặc `ClipboardReadActivity` vào `docs/deployment-guide.md` (rủi ro của phase 1).
