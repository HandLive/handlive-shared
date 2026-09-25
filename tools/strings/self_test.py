"""Tests of check_strings.py on small catalogs and docs written here: every rule must catch its own mistake.

Run: tools/.venv/bin/python tools/strings/check_strings.py --self-test (no hub docs needed).
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

import catalog_rules as rules
import spec_docs

SPEC_IDS = {"0.11", "SET-01", "PAIR-01", "CLIP-01"}


def base_catalog() -> dict:
    """A small catalog that passes every rule: a plain text, a text with an argument, a plural, a plist key."""
    return {
        "version": 1,
        "source_language": "en",
        "languages": ["en", "vi"],
        "strings": [
            {"key": "clipboard.sent_to", "en": "Sent to {device_name}", "vi": "Đã gửi tới {device_name}",
             "comment": "Toast after a manual send", "platforms": ["android", "ios"],
             "args": [{"name": "device_name", "type": "string"}], "specs": ["CLIP-01"]},
            {"key": "common.cancel", "en": "Cancel", "vi": "Hủy", "comment": "Cancel button",
             "platforms": ["android", "macos", "ios"], "specs": ["PAIR-01"]},
            {"key": "infoplist.local_network_usage", "plist_key": "NSLocalNetworkUsageDescription",
             "en": "HandLive looks for your phone on Wi-Fi.", "vi": "HandLive tìm điện thoại trong mạng Wi-Fi.",
             "comment": "Purpose string", "platforms": ["macos", "ios"], "specs": ["SET-01"]},
            {"key": "notification.connected_count",
             "en": {"one": "Connected to {count} device", "other": "Connected to {count} devices"},
             "vi": {"other": "Đã kết nối với {count} thiết bị"}, "comment": "Service notification",
             "platforms": ["android"], "args": [{"name": "count", "type": "int"}], "specs": ["0.11"]},
        ],
    }


def entry(catalog: dict, key: str) -> dict:
    return next(e for e in catalog["strings"] if e["key"] == key)


def mutations():
    """(name, change to the base catalog, text one error must contain)."""

    def set_field(key, name, value):
        return lambda c: entry(c, key).__setitem__(name, value)

    def drop_field(key, name):
        return lambda c: entry(c, key).pop(name)

    def add_entry(**fields):
        return lambda c: c["strings"].append(fields)

    cancel = {"comment": "c", "platforms": ["macos"], "specs": ["PAIR-01"]}
    yield "duplicate key", add_entry(key="notification.connected_count", en="a", vi="b", **cancel), "duplicate key"
    yield "Android name clash", lambda c: (c["strings"].insert(0, dict(key="call.audio_x", en="a", vi="b", **cancel)),
                                           c["strings"].insert(1, dict(key="call_audio.x", en="a", vi="b", **cancel))
                                           ), "same Android resource name"
    yield "unsorted", lambda c: c["strings"].reverse(), "sorted by key"
    yield "missing vi", drop_field("common.cancel", "vi"), "no 'vi' translation"
    yield "unlisted language", set_field("common.cancel", "fr", "Annuler"), "not in \"languages\""
    yield "undeclared placeholder", set_field("common.cancel", "vi", "Hủy {name}"), "is not declared"
    yield "unused argument", set_field("clipboard.sent_to", "vi", "Đã gửi"), "declared but not used"
    yield "stray brace", set_field("common.cancel", "en", "Cancel {"), "brace outside"
    yield "en plural without one", set_field("notification.connected_count", "en", {"other": "{count} devices"}), \
        "CLDR needs"
    yield "vi plural with one", set_field("notification.connected_count", "vi",
                                          {"one": "{count} thiết bị", "other": "{count} thiết bị"}), "CLDR needs"
    yield "plural next to plain text", set_field("notification.connected_count", "vi", "{count} thiết bị"), \
        "plural in en"
    yield "plural without count", set_field("notification.connected_count", "args",
                                            [{"name": "count", "type": "string"}]), "argument named 'count'"
    yield "empty text", set_field("common.cancel", "vi", ""), "empty text"
    yield "blank text", set_field("common.cancel", "vi", "  "), "empty text"
    yield "edge whitespace", set_field("common.cancel", "vi", "Hủy "), "leading or trailing whitespace"
    yield "three dots", set_field("common.cancel", "en", "Cancel..."), "three dots"
    yield "decomposed diacritics", set_field("common.cancel", "vi", "Hủy"), "NFC"
    yield "control character", set_field("common.cancel", "vi", "Hủy\tngay"), "control character"
    yield "new-style tone mark", set_field("common.cancel", "vi", "Huỷ"), "write 'Hủy'"
    yield "plist_key outside infoplist", set_field("common.cancel", "plist_key", "NSFoo"), \
        "only in group infoplist"
    yield "infoplist without plist_key", drop_field("infoplist.local_network_usage", "plist_key"), \
        "needs \"plist_key\""
    yield "unknown spec", set_field("common.cancel", "specs", ["PAIR-09"]), "not a heading"
    yield "bad key", set_field("common.cancel", "key", "Common.Cancel"), "schema: strings/1/key"
    yield "unknown platform", set_field("common.cancel", "platforms", ["windows"]), "schema: strings/1/platforms/0"


class Harness:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
        else:
            self.failed.append(f"{name}{': ' + detail if detail else ''}")
            print(f"  FAIL {name}{': ' + detail if detail else ''}")


def test_catalog_rules(t: Harness, schema: dict) -> None:
    Draft202012Validator.check_schema(schema)
    good = rules.check_catalog(base_catalog(), schema, SPEC_IDS)
    t.check("base catalog passes", not good.errors and not good.warnings, "; ".join(good.errors + good.warnings))
    for name, change, expected in mutations():
        catalog = copy.deepcopy(base_catalog())
        change(catalog)
        result = rules.check_catalog(catalog, schema, SPEC_IDS)
        t.check(f"catches {name}", any(expected in e for e in result.errors),
                f"expected {expected!r}, got {result.errors}")
    catalog = base_catalog()
    entry(catalog, "common.cancel")["en"] = "Cancel."
    result = rules.check_catalog(catalog, schema, SPEC_IDS)
    t.check("warns about different final punctuation",
            not result.errors and any("different punctuation" in w for w in result.warnings), str(result.warnings))
    t.check("spec IDs are optional", not rules.check_catalog(base_catalog(), schema, None).errors)
    try:
        rules.load_json('{"key": "a", "key": "b"}')
        t.check("rejects a repeated field", False, "no error")
    except ValueError as exc:
        t.check("rejects a repeated field", "key" in str(exc), str(exc))


def test_tone_marks(t: Harness) -> None:
    new_style = ["hoá", "xoá", "huỷ", "tuỳ", "thuỷ", "khoẻ", "khoá", "hoà", "hoạ", "thoả", "luỹ", "Huỷ", "HOÁ",
                 "Uỷ", "loè"]
    apple = ["hóa", "xóa", "hủy", "tùy", "thủy", "khỏe", "khóa", "hòa", "họa", "thỏa", "lũy", "quý", "quả", "quỹ",
             "hoàn", "toán", "khoảng", "ngoài", "thuế", "hoặc", "chuyển", "Wi-Fi", "hoạt", "huyết"]
    for word in new_style:
        t.check(f"flags {word}", rules.new_style_words(word) == [word])
    for word in apple:
        t.check(f"accepts {word}", rules.new_style_words(word) == [])
    for word, fixed in [("hoá", "hóa"), ("huỷ", "hủy"), ("khoẻ", "khỏe"), ("Thuỷ", "Thủy"), ("luỹ", "lũy"),
                        ("hoạ", "họa"), ("HOÁ", "HÓA")]:
        t.check(f"suggests {fixed}", rules.apple_style(word) == fixed, rules.apple_style(word))


def test_docs(t: Harness) -> None:
    vi_spec = (
        "# 1. Nhóm chức năng: Thiết lập\n\n## 1.1 SET-01 — Thiết lập ban đầu và cấp quyền\n\n"
        "| 6 | Thông báo | string | Output | \"Đang chờ kết nối\" | \"Đã kết nối qua Wi-Fi với\n"
        "<tên điện thoại>\"<br>Mỗi lần đọc, Android có thể hiện 'HandLive đã dán từ bộ nhớ đệm'. |\n"
        "> Ghi chú: \"Tới 2 thiết bị\" hoặc \"Chưa kết nối\"; nút \"Hủy\" luôn là nút hủy.\n"
    )
    en_spec = ("# 1. Function group: Setup\n\n## 1.1 SET-01 — Initial setup and permissions\n\n"
               "Only the \"Connected via Wi-Fi to <phone name>\" line and \"Cancel\" are shown.\n")
    common = "# 0. Đặc tả dùng chung\n\n## 0.11 Trạng thái kết nối của client\n\n### 0.12.1 Catalog chuỗi\n"
    with tempfile.TemporaryDirectory() as tmp:
        docs = Path(tmp) / "detailed-design"
        docs.mkdir()
        (docs / "00-common-specs.md").write_text(common, encoding="utf-8")
        (docs / "01-setup-settings.md").write_text(vi_spec, encoding="utf-8")
        ids = spec_docs.spec_ids(docs)
        t.check("spec IDs from headings", ids == {"0.11", "0.12.1", "1.1", "SET-01"}, str(sorted(ids)))
        loaded = {d.path.name: d.lang for d in spec_docs.load_docs([docs])}
        t.check("a lone Vietnamese X.md reads as vi", loaded.get("01-setup-settings.md") == "vi", str(loaded))

        catalog = {"languages": ["en", "vi"], "strings": [
            {"key": "status.connected_wifi_to", "en": "Connected via Wi-Fi to {device_name}",
             "vi": "Đã kết nối qua Wi-Fi với {device_name}"},
            {"key": "clipboard.consent_toast", "en": "x", "vi": "Mỗi lần đọc, Android có thể hiện “HandLive đã dán "
                                                                "từ bộ nhớ đệm”."},
            {"key": "clipboard.tile_count", "en": {"one": "To {count} device", "other": "To {count} devices"},
             "vi": {"other": "Tới {count} thiết bị"}},
            {"key": "common.cancel", "en": "Cancel", "vi": "Hủy"},
            {"key": "status.waiting", "en": "Waiting for a connection", "vi": "Đang chờ kết nối."},
            {"key": "common.on", "en": "On", "vi": "Bật"},
        ]}
        missing, count = spec_docs.missing_from_docs(catalog, spec_docs.load_docs([docs]))
        t.check("vi found across wraps, <br>, placeholders, quotes, plurals and an optional period",
                missing["vi"] == ["common.on"], str(missing["vi"]))
        t.check("en skipped while no English spec exists", count["en"] == 0 and missing["en"] == [], str(count))

        (docs / "01-setup-settings.vi.md").write_text(vi_spec, encoding="utf-8")
        (docs / "01-setup-settings.md").write_text(en_spec, encoding="utf-8")
        loaded = {d.path.name: d.lang for d in spec_docs.load_docs([docs])}
        t.check("X.md with a .vi.md twin reads as en", loaded.get("01-setup-settings.md") == "en", str(loaded))
        t.check("X.vi.md reads as vi", loaded.get("01-setup-settings.vi.md") == "vi", str(loaded))
        missing, count = spec_docs.missing_from_docs(catalog, spec_docs.load_docs([docs]))
        t.check("en searched in the English spec only; 'On' is not matched inside 'Only'",
                missing["en"] == ["clipboard.consent_toast", "clipboard.tile_count", "status.waiting", "common.on"],
                str(missing["en"]))
        t.check("spec IDs read from both twins", "SET-01" in spec_docs.spec_ids(docs))


def main(schema: dict) -> int:
    t = Harness()
    test_catalog_rules(t, schema)
    test_tone_marks(t)
    test_docs(t)
    print(f"self-test: {t.passed} passed, {len(t.failed)} failed")
    return 1 if t.failed else 0
