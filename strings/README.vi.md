[English](README.md) | Tiếng Việt

# Catalog chuỗi giao diện

`ui-strings.json` là nguồn duy nhất của mọi chuỗi hiển thị của HandLive trên Android, macOS và iOS/iPadOS: nhãn, nút, menu, thông báo, tên kênh thông báo, purpose string xin quyền, nhãn trợ năng và câu lỗi (quyết định C20, `../docs/detailed-design/00-common-specs.md` mục 0.12). Tiếng Anh (`en`) là ngôn ngữ mặc định, ngôn ngữ nguồn và ngôn ngữ dự phòng; tiếng Việt (`vi`) là ngôn ngữ thứ hai. Mã không chứa câu chữ hiển thị: mỗi nền tảng sinh tài nguyên từ file này.

| File | Nội dung |
|------|----------|
| `ui-strings.json` | Catalog: `version`, `source_language` (`en`), `languages` (`en`, `vi`), `strings` |
| `ui-strings.schema.json` | JSON Schema 2020-12 của catalog |
| `../tools/strings/check_strings.py` | Công cụ kiểm theo 0.12.5 (xem dưới) |

## Một mục

```json
{
  "key": "pairing.paired_with",
  "en": "Paired with {device_name}",
  "vi": "Đã ghép nối với {device_name}",
  "comment": "Feedback on both devices when pairing succeeds (HUD, sheet); {device_name} is the peer",
  "platforms": ["android", "macos", "ios"],
  "args": [{"name": "device_name", "type": "string"}],
  "specs": ["PAIR-01"]
}
```

| Trường | Quy tắc |
|--------|---------|
| `key` | Chữ thường `[a-z0-9_]`, 2–5 đoạn nối bằng dấu chấm. Đoạn đầu là nhóm: `common`, `setup`, `settings`, `pairing`, `status`, `menu`, `clipboard`, `sms`, `call`, `call_audio`, `camera`, `permission`, `notification`, `push`, `error`, `a11y`, `infoplist`. Sửa câu chữ thì giữ khóa; đổi nghĩa thì tạo khóa mới. Khóa vẫn duy nhất sau khi đổi `.` thành `_` (tên tài nguyên Android). |
| `en`, `vi` | Chuỗi, hoặc object số nhiều theo CLDR: `en` có `one` và `other`, `vi` chỉ có `other`. Có đủ mọi ngôn ngữ trong `languages`, không rỗng. |
| `args` | Tham số `{tên}` với `type` là `string`, `int` hoặc `double`. Mọi bản dịch dùng đúng cùng một tập, thứ tự trong câu tự do (bộ sinh đổi sang tham số có vị trí). Ngày, giờ, số, dung lượng, thời lượng được formatter của hệ thống định dạng trước khi truyền vào, nên có kiểu `string`. |
| `comment` | Bắt buộc: chuỗi xuất hiện ở đâu, giới hạn độ dài nếu có — ngữ cảnh cho người dịch. |
| `platforms` | Tập con của `android`, `macos`, `ios`: bộ sinh của các nền tảng này lấy chuỗi. |
| `specs` | Mã chức năng lá (`CLIP-01`) hoặc mục của `00-common-specs` (`0.11`) đặc tả chuỗi; phải có trong tiêu đề của `../docs/detailed-design`. |
| `plist_key` | Chỉ nhóm `infoplist`, và bắt buộc ở nhóm đó: tên khóa Info.plist (purpose string). |

Quy ước riêng của kho này, thêm vào 0.12.1:

- Các mục xếp theo khóa (thứ tự điểm mã, như `sorted()` của Python), để phần thêm từ nhiều nhánh gộp không xung đột.
- Số nhiều được chọn theo tham số `int` tên `count`.
- Dấu ngoặc kép trong câu là dấu kiểu chữ in: “…” (cả hai ngôn ngữ).
- Câu tài liệu chưa ghi thì `comment` nói rõ ("Proposed text"); phải đưa vào tài liệu trước khi phát hành.

## Viết

Theo design system, mục "Viết nội dung" (`../docs/design-system/1-foundations/09-viet-noi-dung.md`), cả phần tiếng Anh:

- Tiếng Anh: viết hoa kiểu tiêu đề cho nút, mục menu, tiêu đề cửa sổ và sheet, tab, nhãn dòng cài đặt, tiêu đề alert và thông báo ("Send Clipboard to Phone", "Pair with {device_name}?"): viết hoa mọi từ trừ mạo từ (a, an, the), liên từ đẳng lập (and, but, or, nor, for, so, yet) và giới từ từ bốn chữ cái trở xuống (at, by, for, from, in, into, of, off, on, onto, out, over, to, up, via, with) khi không đứng đầu hay cuối; viết hoa kiểu câu cho mô tả, chú thích, nội dung alert, nội dung thông báo, chuỗi trạng thái và tooltip ("Connected via Wi-Fi"). Ngắn, chủ động, thì hiện tại; không "please", "sorry", dấu chấm than hay emoji.
- Tiếng Việt: viết hoa đầu câu ở mọi chỗ; bỏ dấu kiểu Apple (hóa, xóa, hủy, tùy, thủy, khỏe — không viết hoá, xoá, huỷ, tuỳ); thuật ngữ "bảng nhớ tạm", "kết nối qua Internet", "Mã an toàn".
- Cả hai: ký tự "…", không gõ ba dấu chấm; tên riêng không dịch (HandLive, Wi-Fi, Bluetooth, USB, SIM, Mac, iPhone, iPad, Android); tên mục cài đặt hệ thống viết đúng như hệ điều hành hiển thị ở ngôn ngữ đó ("System Settings › Privacy & Security" / "Cài đặt hệ thống › Quyền riêng tư & Bảo mật", Android "Accessibility" / "Hỗ trợ tiếp cận").
- Nội dung của người dùng (tin SMS, tên thiết bị, tên liên hệ) không bao giờ dịch; chỉ điền vào tham số.

## Nền tảng dùng thế nào (0.12.2)

| Nền tảng | Đầu ra | Ánh xạ |
|----------|--------|--------|
| Android | `values/strings.xml` (en, mặc định) và `values-vi/strings.xml`, do task Gradle trong `buildSrc` sinh vào thư mục build | tên tài nguyên = khóa đổi `.` thành `_`; số nhiều thành `<plurals>`; `{tên}` thành `%1$s` / `%1$d` theo thứ tự `args`; thoát `'`, `"`, `@` và `?` đầu chuỗi và xuống dòng; `%` thường thành `%%` |
| Apple | `Localizable.xcstrings`, `InfoPlist.xcstrings` (ngôn ngữ nguồn en) và accessor Swift, do script trong `apple/` sinh và commit | khóa giữ dấu chấm; số nhiều thành biến thể plural của String Catalog; `{tên}` thành `%1$@` / `%1$lld`; `infoplist.*` vào `InfoPlist.xcstrings` theo `plist_key` |

Push APNs chỉ mang một khóa `push.*` trong `aps.alert.loc-key`; iPhone hiện bằng ngôn ngữ của nó (CONN-04). Mã lỗi của giao thức ứng với câu nhóm `error.*`; `message` của lỗi là chuỗi chẩn đoán tiếng Anh cho log (0.12.4).

## Thêm hoặc sửa một chuỗi

1. Sửa tài liệu trước, ở kho hub: câu tiếng Anh trong `X.md`, câu tiếng Việt trong `X.vi.md` (cùng commit).
2. Sửa `ui-strings.json` trong một commit riêng ở kho này và chạy công cụ kiểm. Khi nhiều agent hoặc nhiều người cùng sửa kho này, giữ khóa của workspace quanh commit: `mkdir ../.locks/shared` (lỗi khi người khác đang giữ), commit, rồi `rmdir ../.locks/shared`.
3. Sửa mã; mã chỉ đọc tài nguyên đã sinh.

## Kiểm tra

Chạy từ gốc kho này bằng venv của tools (`python3 -m venv tools/.venv && tools/.venv/bin/python -m pip install -r tools/strings/requirements.txt`):

```sh
tools/.venv/bin/python tools/strings/check_strings.py              # quy tắc 0.12.5; in OK, thoát 1 khi có lỗi
tools/.venv/bin/python tools/strings/check_strings.py --docs       # cảnh báo thêm câu tài liệu không ghi
tools/.venv/bin/python tools/strings/check_strings.py --self-test  # tự kiểm công cụ
```

Lỗi: schema; khóa duy nhất (kể cả sau khi đổi `.` thành `_`) và đúng thứ tự; đủ mọi ngôn ngữ; cùng tập tham số, không dấu ngoặc nhọn lạc; loại số nhiều theo CLDR kèm tham số `int` tên `count`; không chuỗi rỗng, không khoảng trắng đầu hoặc cuối, dạng NFC, không ký tự điều khiển, "…" thay "..."; dấu kiểu Apple trong `vi`; `plist_key` đúng ở nhóm `infoplist`; mã trong `specs` có thật trong `../docs/detailed-design` (ghi đè bằng `HANDLIVE_DOCS_DIR` hoặc `--docs DIR`). Cảnh báo: các bản dịch kết thúc bằng dấu câu khác nhau; mạo từ, liên từ đẳng lập hoặc giới từ ngắn bị viết hoa giữa một chuỗi tiếng Anh viết hoa kiểu tiêu đề.

`--docs` tìm từng câu `vi` trong tài liệu tiếng Việt và từng câu `en` trong tài liệu tiếng Anh, trong `docs/detailed-design` và `docs/design-system`: `X.md` là tiếng Anh khi có bản `X.vi.md`; `X.md` đứng một mình được tính theo ngôn ngữ nó đang viết (tài liệu đang được dịch). Tham số khớp với ví dụ hoặc với `<tên>` tài liệu ghi ở chỗ đó, dấu chấm cuối câu không bắt buộc. Câu không tìm thấy chỉ là cảnh báo. CI (`ci-shared`) chạy tự kiểm và `--docs`; `tools/schemas/check_schemas.py` còn kiểm đoạn catalog trích trong 0.12.1.
