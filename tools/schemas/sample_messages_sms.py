"""Hand-written samples for the SMS, clipboard and SMS notification schemas.

POSITIVE samples use real values (no placeholders) and must pass; each NEGATIVE sample changes one thing in a
positive sample and must be rejected because of exactly that change. Same shape as sample_messages.py:
(name, schema, instance).
"""

from __future__ import annotations

import copy

UUID_V7 = "0192f3e0-1a2b-7c3d-8e4f-5a6b7c8d9e01"
LOCAL_ID = "0192f3e2-4b5c-7d6e-9f70-8a9b0c1d2e3f"
CLIP_ID = "0192f3e0-5a21-7b3c-9d4e-1f2a3b4c5d6e"
TRANSFER_ID = "0192f3f1-2c3e-7a10-9b20-c30d40e50f60"
PAIR_ID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
DEVICE_C = "5b1f8c2e-9a4d-8e6f-a1b2-c3d4e5f60718"
DEVICE_S = "8c7d6e5f-4a3b-8c2d-9e1f-0a1b2c3d4e5f"
CURSOR = "eyJ2IjoxLCJpZCI6MTI4NDYsInQiOjE3MjcxNTAwMDAxMjN9"
PAGE_TOKEN = "eyJ2IjoxLCJtIjoxMjg0NiwiYSI6MTI3OTB9"
SHA256 = "n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg"

THREAD = {"thread_id": 42, "addresses": ["+84900000123"], "display_name": None, "snippet": "Ok",
          "last_ts": 1727150060456, "unread_count": 1}
MESSAGE = {"message_key": "sms:12847", "thread_id": 42, "address": "+84900000123", "body": "Ok", "box": "inbox",
           "ts": 1727150060456, "ts_sent": None, "read": False, "sub_id": None}
SENT_WITH_LOCAL_ID = {**MESSAGE, "message_key": "sms:12848", "box": "sent", "read": True, "sub_id": 2,
                      "local_id": LOCAL_ID}

POSITIVE = [
    ("sms/sync first page", "sms-sync", {"op": "sync", "data": {"thread_limit": 200, "per_thread_limit": 50}}),
    ("sms/sync loop", "sms-sync", {"op": "sync", "data": {"cursor": CURSOR, "page_token": PAGE_TOKEN,
                                                          "thread_limit": 500, "per_thread_limit": 1}}),
    ("sms/sync ack with more pages", "sms-sync#ack",
     {"re": UUID_V7, "ok": True, "data": {"threads": [THREAD], "messages": [MESSAGE], "cursor": CURSOR,
                                          "page_token": PAGE_TOKEN, "has_more": True}}),
    ("sms/sync ack last page", "sms-sync#ack",
     {"re": UUID_V7, "ok": True, "data": {"threads": [], "messages": [], "cursor": CURSOR, "has_more": False,
                                          "unread": [{"thread_id": 42, "unread_count": 1,
                                                      "read_up_to_ts": 1727150060455}]}}),
    ("sms/history", "sms-history", {"op": "history", "data": {"thread_id": 42, "before_ts": 1727140000000,
                                                              "limit": 50}}),
    ("sms/history ack", "sms-history#ack",
     {"re": UUID_V7, "ok": True, "data": {"messages": [MESSAGE], "has_more": False}}),
    ("sms/new received", "sms-new", {"op": "new", "data": {"message": MESSAGE, "thread": THREAD}}),
    ("sms/new with local_id", "sms-new", {"op": "new", "data": {"message": SENT_WITH_LOCAL_ID, "thread": THREAD}}),
    ("sms/send", "sms-send", {"op": "send", "data": {"local_id": LOCAL_ID, "thread_id": 42,
                                                     "addresses": ["+84900000123"], "body": "Ok", "sub_id": 1}}),
    ("sms/send new number", "sms-send", {"op": "send", "data": {"local_id": LOCAL_ID, "addresses": ["1414"],
                                                                "body": "x" * 1600}}),
    ("sms/send ack", "sms-send#ack", {"re": UUID_V7, "ok": True, "data": {"accepted": True, "parts": 2}}),
    ("sms/send error ack", "ack", {"re": UUID_V7, "ok": False,
                                   "error": {"code": "SMS_SIM_UNAVAILABLE", "message": "Selected SIM is not active",
                                             "details": {"sims": [1, 2]}}}),
    ("sms/status sent", "sms-status", {"op": "status", "data": {"local_id": LOCAL_ID, "message_key": "sms:12848",
                                                                "status": "sent"}}),
    ("sms/status failed", "sms-status", {"op": "status", "data": {"local_id": LOCAL_ID, "status": "failed",
                                                                  "error_code": "SMS_RADIO_OFF"}}),
    ("sms/read_changed", "sms-read_changed", {"op": "read_changed", "data": {"thread_id": 42, "unread_count": 0,
                                                                            "read_up_to_ts": 1727150130000}}),
    ("SMS notification", "sms-notification",
     {"identifier": f"sms:{PAIR_ID}:sms:12847", "title": "+84 90 000 01 23", "subtitle": "SIM 2", "body": "Ok",
      "threadIdentifier": f"sms:{PAIR_ID}:42", "categoryIdentifier": "HL_SMS", "sound": "default",
      "userInfo": {"pair_id": PAIR_ID, "thread_id": 42, "message_key": "sms:12847", "ts": 1727150060456,
                   "address": "+84900000123", "sub_id": None}}),
    ("SMS notification group conversation", "sms-notification",
     {"identifier": f"sms:{PAIR_ID}:sms:12851", "title": "Nguyễn Văn A, +84 90 000 04 56", "subtitle": "",
      "body": "Hẹn 7 giờ nhé", "threadIdentifier": f"sms:{PAIR_ID}:57", "categoryIdentifier": "HL_SMS_GROUP",
      "sound": "default",
      "userInfo": {"pair_id": PAIR_ID, "thread_id": 57, "message_key": "sms:12851", "ts": 1727150070000,
                   "address": "+84900000123", "sub_id": 1}}),
    ("clipboard/push text", "clipboard-push",
     {"op": "push", "data": {"clip_id": CLIP_ID, "kind": "text", "mime": "text/plain", "text": "Hello",
                             "sensitive": False, "origin_ts": 1727150300789, "source": "ios",
                             "origin_device_id": DEVICE_C}}),
    ("clipboard/push image", "clipboard-push",
     {"op": "push", "data": {"clip_id": CLIP_ID, "kind": "image", "mime": "image/png",
                             "transfer": {"transfer_id": TRANSFER_ID, "size": 5242880, "sha256": SHA256,
                                          "chunk_size": 65536, "chunk_count": 80},
                             "width": 2880, "height": 1800, "sensitive": False, "origin_ts": 1727150200456,
                             "source": "mac", "origin_device_id": DEVICE_C}}),
    ("clipboard/push chunked text", "clipboard-push",
     {"op": "push", "data": {"clip_id": CLIP_ID, "kind": "text", "mime": "text/plain",
                             "transfer": {"transfer_id": TRANSFER_ID, "size": 400000, "sha256": SHA256,
                                          "chunk_size": 65536, "chunk_count": 7},
                             "sensitive": True, "origin_ts": 1727150200456, "source": "auto",
                             "origin_device_id": DEVICE_S}}),
    ("clipboard/push ack applied", "clipboard-push#ack",
     {"re": UUID_V7, "ok": True, "data": {"clip_id": CLIP_ID, "status": "applied"}}),
    ("clipboard/push ack ignored", "clipboard-push#ack",
     {"re": UUID_V7, "ok": True, "data": {"clip_id": CLIP_ID, "status": "ignored", "reason": "duplicate"}}),
    ("clipboard/conflict", "clipboard-conflict",
     {"op": "conflict", "data": {"clip_id": CLIP_ID, "origin_device_id": DEVICE_C, "device_id": DEVICE_S,
                                 "device_name": "Pixel của Lan"}}),
]


def _variant(base_name: str, change) -> dict:
    instance = copy.deepcopy(next(inst for name, _, inst in POSITIVE if name == base_name))
    change(instance)
    return instance


def _set(path: list, value):
    def apply(instance):
        for key in path[:-1]:
            instance = instance[key]
        instance[path[-1]] = value
    return apply


def _drop(path: list):
    def apply(instance):
        for key in path[:-1]:
            instance = instance[key]
        del instance[path[-1]]
    return apply


# (name, schema, positive sample it starts from, change).
NEGATIVE_SPECS = [
    ("sms/sync thread_limit 501", "sms-sync", "sms/sync first page", _set(["data", "thread_limit"], 501)),
    ("sms/sync per_thread_limit 0", "sms-sync", "sms/sync first page", _set(["data", "per_thread_limit"], 0)),
    ("sms/sync without thread_limit", "sms-sync", "sms/sync first page", _drop(["data", "thread_limit"])),
    ("sms/sync cursor not b64u", "sms-sync", "sms/sync loop", _set(["data", "cursor"], CURSOR + "=")),
    ("sms/sync ack more pages without page_token", "sms-sync#ack", "sms/sync ack with more pages",
     _drop(["data", "page_token"])),
    ("sms/sync ack more pages with unread", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "unread"], [])),
    ("sms/sync ack last page without unread", "sms-sync#ack", "sms/sync ack last page", _drop(["data", "unread"])),
    ("sms/sync ack last page with page_token", "sms-sync#ack", "sms/sync ack last page",
     _set(["data", "page_token"], PAGE_TOKEN)),
    ("sms/sync ack unread entry with 0", "sms-sync#ack", "sms/sync ack last page",
     _set(["data", "unread", 0, "unread_count"], 0)),
    ("sms/sync ack message with local_id", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "messages", 0, "local_id"], LOCAL_ID)),
    ("sms/sync ack message box draft", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "messages", 0, "box"], "draft")),
    ("sms/sync ack message_key without prefix", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "messages", 0, "message_key"], "12847")),
    ("sms/sync ack snippet over 160", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "threads", 0, "snippet"], "x" * 161)),
    ("sms/sync ack thread without display_name", "sms-sync#ack", "sms/sync ack with more pages",
     _drop(["data", "threads", 0, "display_name"])),
    ("sms/sync ack thread without address", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "threads", 0, "addresses"], [])),
    ("sms/sync ack sub_id -1", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "messages", 0, "sub_id"], -1)),
    ("sms/sync ack 501 messages", "sms-sync#ack", "sms/sync ack with more pages",
     _set(["data", "messages"], [MESSAGE] * 501)),
    ("sms/history limit 201", "sms-history", "sms/history", _set(["data", "limit"], 201)),
    ("sms/history without before_ts", "sms-history", "sms/history", _drop(["data", "before_ts"])),
    ("sms/history ack message with local_id", "sms-history#ack", "sms/history ack",
     _set(["data", "messages", 0, "local_id"], LOCAL_ID)),
    ("sms/new without thread", "sms-new", "sms/new received", _drop(["data", "thread"])),
    ("sms/new local_id not v7", "sms-new", "sms/new with local_id",
     _set(["data", "message", "local_id"], PAIR_ID)),
    ("sms/send two recipients", "sms-send", "sms/send", _set(["data", "addresses"], ["+84900000123", "+84900000124"])),
    ("sms/send empty body", "sms-send", "sms/send", _set(["data", "body"], "")),
    ("sms/send whitespace body", "sms-send", "sms/send", _set(["data", "body"], " \n ")),
    ("sms/send body 1601", "sms-send", "sms/send new number", _set(["data", "body"], "x" * 1601)),
    ("sms/send sub_id null", "sms-send", "sms/send", _set(["data", "sub_id"], None)),
    ("sms/send without local_id", "sms-send", "sms/send", _drop(["data", "local_id"])),
    ("sms/send ack accepted false", "sms-send#ack", "sms/send ack", _set(["data", "accepted"], False)),
    ("sms/send ack 0 parts", "sms-send#ack", "sms/send ack", _set(["data", "parts"], 0)),
    ("sms/status failed without error_code", "sms-status", "sms/status failed", _drop(["data", "error_code"])),
    ("sms/status sent with error_code", "sms-status", "sms/status sent",
     _set(["data", "error_code"], "SMS_NO_SERVICE")),
    ("sms/status error_code outside the send errors", "sms-status", "sms/status failed",
     _set(["data", "error_code"], "SMS_SIM_UNAVAILABLE")),
    ("sms/status pending", "sms-status", "sms/status sent", _set(["data", "status"], "pending")),
    ("sms/read_changed negative count", "sms-read_changed", "sms/read_changed",
     _set(["data", "unread_count"], -1)),
    ("sms/read_changed without read_up_to_ts", "sms-read_changed", "sms/read_changed",
     _drop(["data", "read_up_to_ts"])),
    ("SMS notification identifier without message_key", "sms-notification", "SMS notification",
     _set(["identifier"], f"sms:{PAIR_ID}:12847")),
    ("SMS notification userInfo without ts", "sms-notification", "SMS notification", _drop(["userInfo", "ts"])),
    ("SMS notification other category", "sms-notification", "SMS notification",
     _set(["categoryIdentifier"], "HL_CALL")),
    ("SMS notification category SMS-02 does not define", "sms-notification", "SMS notification group conversation",
     _set(["categoryIdentifier"], "HL_SMS_GROUP_REPLY")),
    ("clipboard/push text and transfer", "clipboard-push", "clipboard/push image",
     _set(["data", "text"], "Hello")),
    ("clipboard/push image without transfer", "clipboard-push", "clipboard/push image",
     _drop(["data", "transfer"])),
    ("clipboard/push image without width", "clipboard-push", "clipboard/push image", _drop(["data", "width"])),
    ("clipboard/push text with image mime", "clipboard-push", "clipboard/push text",
     _set(["data", "mime"], "image/png")),
    ("clipboard/push text with height", "clipboard-push", "clipboard/push text", _set(["data", "height"], 10)),
    ("clipboard/push chunk_size 32768", "clipboard-push", "clipboard/push image",
     _set(["data", "transfer", "chunk_size"], 32768)),
    ("clipboard/push unknown source", "clipboard-push", "clipboard/push text", _set(["data", "source"], "ipad")),
    ("clipboard/push ack ignored without reason", "clipboard-push#ack", "clipboard/push ack ignored",
     _drop(["data", "reason"])),
    ("clipboard/push ack applied with reason", "clipboard-push#ack", "clipboard/push ack applied",
     _set(["data", "reason"], "conflict")),
    ("clipboard/conflict name over 64", "clipboard-conflict", "clipboard/conflict",
     _set(["data", "device_name"], "x" * 65)),
]

NEGATIVE = [(name, schema, _variant(base, change)) for name, schema, base, change in NEGATIVE_SPECS]
