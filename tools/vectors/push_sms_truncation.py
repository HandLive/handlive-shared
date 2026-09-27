"""SMS text cut for a push to an iPhone/iPad (CONN-04 step 5b, SMS-02 API 2 logic 3), generator side.

The rule the vectors pin. Lengths are Unicode code points (0.3 string(n)), never UTF-16 units or grapheme clusters;
cut(text, m) is text when it has at most m code points, else its first m − 1 code points followed by "…".
1. body_to_1000: a message.body over 1,000 code points becomes cut(body, 1000).
2. body_to_fit: while env_b64 is over 3,000 characters, message.body becomes cut(body, m) for the largest m below its
   current code-point count that fits (the longest cut that fits).
3. body_to_ellipsis, snippet_to_fit: when not even "…" fits, message.body stays "…" and thread.snippet is cut the
   same way (the snippet is the newest body cut to 160 code points without "…", SMS-01 API 1).
When nothing fits the phone sends no push and the message arrives with SMS-01; the vectors never reach that case.
The plaintext is compact UTF-8 JSON (non-ASCII written as UTF-8, never as \\u escapes), so its byte length, and with
it the env_b64 length, is the same on every platform.
"""
from __future__ import annotations

import copy
from typing import Callable

from handlive_protocol_derivations import test_bytes

ELLIPSIS = "…"
BODY_MAX = 1000
SNIPPET_MAX = 160
ENV_B64_MAX = 3000

VI_SENTENCE = "Chiều nay 3 giờ họp ở phòng số 2, nhớ mang theo tài liệu và máy tính nhé. "
EN_SENTENCE = "Meeting moved to 3 pm in room 2. Please bring the printed agenda and your laptop. "
GROUP_TEXT = ("Cả nhóm ơi, sáng mai 7 giờ tập trung ở cổng trường, mỗi người mang theo nước uống, áo mưa và giấy tờ "
              "tùy thân. Ai chưa đóng tiền xe thì chuyển khoản cho Bình trước 9 giờ tối nay nhé.")
FAMILY_NAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ"]
GIVEN_NAMES = ["An", "Bình", "Châu", "Dũng"]
GROUP_SIZE = 42


def cut(text: str, m: int) -> str:
    return text if len(text) <= m else text[:max(m - 1, 0)] + ELLIPSIS


def uuid7(ts_ms: int, label: str) -> str:
    """UUIDv7 whose 48-bit prefix is ts_ms; the other bits come from test_bytes(label)."""
    r = test_bytes(label, 10)
    h = (ts_ms.to_bytes(6, "big") + bytes([0x70 | (r[0] & 0x0F), r[1], 0x80 | (r[2] & 0x3F)]) + r[3:]).hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def sms_new(message_key: str, thread_id: int, address: str, body: str, ts: int, ts_sent: int | None,
            sub_id: int | None, addresses: list[str], display_name: str | None, unread_count: int) -> dict:
    """The sms/new plaintext SMS-02 API 1 sends, before any push cut; the snippet is the body cut to 160."""
    return {"op": "new", "data": {
        "message": {"message_key": message_key, "thread_id": thread_id, "address": address, "body": body,
                    "box": "inbox", "ts": ts, "ts_sent": ts_sent, "read": False, "sub_id": sub_id},
        "thread": {"thread_id": thread_id, "addresses": addresses, "display_name": display_name,
                   "snippet": body[:SNIPPET_MAX], "last_ts": ts, "unread_count": unread_count}}}


def _longest_fitting(text: str, fits: Callable[[str], bool]) -> str | None:
    for m in range(len(text) - 1, 0, -1):
        if fits(cut(text, m)):
            return cut(text, m)
    return None


def truncate(new: dict, env_b64_length: Callable[[dict], int]) -> tuple[dict, list[str]]:
    """The sms/new object to seal for a push and the steps applied (rule in the module docstring)."""
    out = copy.deepcopy(new)
    message, thread = out["data"]["message"], out["data"]["thread"]
    steps = []

    def fits_with(body: str, snippet: str) -> bool:
        return env_b64_length({"op": out["op"], "data": {"message": {**message, "body": body},
                                                         "thread": {**thread, "snippet": snippet}}}) <= ENV_B64_MAX

    if len(message["body"]) > BODY_MAX:
        message["body"] = cut(message["body"], BODY_MAX)
        steps.append("body_to_1000")
    if fits_with(message["body"], thread["snippet"]):
        return out, steps
    body = _longest_fitting(message["body"], lambda b: fits_with(b, thread["snippet"]))
    if body is not None:
        message["body"] = body
        return out, steps + ["body_to_fit"]
    message["body"] = cut(message["body"], 1)
    snippet = _longest_fitting(thread["snippet"], lambda s: fits_with(message["body"], s))
    assert snippet is not None, "the vectors never reach the no-push case"
    thread["snippet"] = snippet
    return out, steps + ["body_to_ellipsis", "snippet_to_fit"]


def _group() -> tuple[list[str], str]:
    addresses = [f"+849{1234000 + i * 37:08d}" for i in range(GROUP_SIZE)]
    names = [f"{family} {given}" for given in GIVEN_NAMES for family in FAMILY_NAMES][:GROUP_SIZE]
    return addresses, ", ".join(names)


def cases() -> list[tuple[str, int, dict]]:
    """(vector name, envelope ts, sms/new before the cut) for the push-envelope.json cut vectors."""
    long_en = (EN_SENTENCE * 15).rstrip()
    group_addresses, group_names = _group()
    out = [
        ("pair 2 / sms/new, Vietnamese body over 1,000 characters, cut further until env_b64 fits", 1727150100060,
         sms_new("sms:12860", 42, "+84900000123", (VI_SENTENCE * 17).rstrip(), 1727150100000, 1727150098000, 1,
                 ["+84900000123"], "Nguyễn Văn A", 3)),
        ("pair 2 / sms/new, ASCII body over 1,000 characters, cut at 1,000", 1727150110050,
         sms_new("sms:12861", 63, "+84900000789", long_en, 1727150110000, 1727150109000, 1, ["+84900000789"],
                 None, 1)),
        ("pair 2 / sms/new, body of exactly 1,000 characters, not cut", 1727150120050,
         sms_new("sms:12862", 63, "+84900000789", long_en[:999] + ".", 1727150120000, 1727150119000, 1,
                 ["+84900000789"], None, 2)),
        ("pair 2 / sms/new, emoji at the 1,000-character cut (code points, not UTF-16 units)", 1727150130050,
         sms_new("sms:12863", 64, "+84900000456", long_en[:997] + "🎉" * 10, 1727150130000, 1727150129000, 1,
                 ["+84900000456"], "Lê Thị B", 1)),
        ("pair 2 / sms/new, crowded group conversation: body down to \"…\", then the snippet cut", 1727150140050,
         sms_new("sms:12864", 70, group_addresses[3], GROUP_TEXT, 1727150140000, 1727150139000, 2, group_addresses,
                 group_names, 1)),
    ]
    return out


def describe(new: dict, sealed: dict, steps: list[str], env_b64_length: Callable[[dict], int]) -> dict:
    """The truncation object of a cut vector: the texts before the cut, the steps, and the lengths that prove the
    last cut is the longest that fits (one more code point kept would push env_b64 over 3,000)."""
    before, after = new["data"], sealed["data"]
    body, snippet = after["message"]["body"], after["thread"]["snippet"]
    info = {"original_body": before["message"]["body"], "original_snippet": before["thread"]["snippet"],
            "steps": steps, "body_code_points": len(body), "body_utf16_units": len(body.encode("utf-16-le")) // 2,
            "snippet_code_points": len(snippet), "env_b64_length": env_b64_length(sealed)}
    wider = copy.deepcopy(sealed)
    if steps[-1:] == ["body_to_fit"]:
        wider["data"]["message"]["body"] = cut(cut(before["message"]["body"], BODY_MAX), len(body) + 1)
    elif steps[-1:] == ["snippet_to_fit"]:
        wider["data"]["thread"]["snippet"] = cut(before["thread"]["snippet"], len(snippet) + 1)
    else:
        return info
    info["one_more_code_point_env_b64_length"] = env_b64_length(wider)
    return info
