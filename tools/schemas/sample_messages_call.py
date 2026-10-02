"""Hand-written samples for the call schemas (call_event-*, call-notification), app calls (CALL-05) included.

POSITIVE samples use real values (no placeholders) and must pass; each NEGATIVE sample changes one thing in a
positive sample and must be rejected because of exactly that change. Same shape as sample_messages.py:
(name, schema, instance).
"""

from __future__ import annotations

import copy

CALL_ID = "0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90"
OTHER_CALL_ID = "0192f3f5-1b2c-7d3e-9f4a-5b6c7d8e9f00"
REQUEST_ID = "0192f3f1-0b2c-7d3e-8f4a-5b6c7d8e9f01"
PAIR_ID = "7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d"
CURSOR = "eyJ2IjoxLCJpZCI6NTEyMH0"
EMPTY_LOG_CURSOR = "eyJ2IjoxLCJpZCI6MH0"
NO_CONTROLS = {"answer": False, "reject": False, "end": False, "hold": "unavailable", "dtmf": "unavailable",
               "mute": "unavailable"}

RINGING = {
    "call_id": CALL_ID, "direction": "incoming", "state": "ringing", "waiting": False, "number": "+84900000123",
    "display_name": "Nguyễn Văn A", "presentation": "allowed", "sub_id": 1, "sim_label": "SIM 1",
    "waiting_number": None, "waiting_display_name": None, "started_at": 1727150400123, "answered_at": None,
    "ended_at": None, "end_reason": None,
    "controls": {**NO_CONTROLS, "answer": True, "reject": True}, "hfp_connected": False, "audio_on": "phone",
}
OFFHOOK = {**RINGING, "state": "offhook", "answered_at": 1727150405321,
           "controls": {**NO_CONTROLS, "end": True}}
OFFHOOK_HFP = {**OFFHOOK, "controls": {**NO_CONTROLS, "end": True, "hold": "hfp", "dtmf": "hfp", "mute": "hfp"},
               "hfp_connected": True, "audio_on": "mac"}
WAITING = {**OFFHOOK, "state": "ringing", "waiting": True, "waiting_number": "+84900000456",
           "waiting_display_name": None, "controls": NO_CONTROLS}
OUTGOING = {**RINGING, "direction": "outgoing", "state": "offhook", "number": None, "display_name": None,
            "presentation": "unknown", "controls": {**NO_CONTROLS, "end": True}}
MISSED = {**RINGING, "state": "idle", "ended_at": 1727150425456, "end_reason": "missed", "controls": NO_CONTROLS}
ENTRY = {"entry_id": 5120, "number": "+84900000123", "display_name": "Nguyễn Văn A", "type": "missed",
         "ts": 1727150400123, "duration_s": 0, "sub_id": 1}
WITHHELD_ENTRY = {"entry_id": 5121, "number": None, "display_name": None, "type": "rejected", "ts": 1727150500000,
                  "duration_s": 0, "sub_id": None}
APP_CALL_ID = "0192f3f6-2c3d-7e4f-8a5b-6c7d8e9f0a1b"
NO_APP_CONTROLS = {"answer": False, "decline": False, "end": False}
APP_RINGING = {
    "call_id": APP_CALL_ID, "app": {"package": "org.telegram.messenger", "label": "Telegram"},
    "caller": "Nguyễn Văn A", "state": "ringing", "controls": {"answer": True, "decline": True, "end": False},
    "answer_mode": "direct", "audio": "phone", "started_at": 1727150400123, "answered_at": None, "ended_at": None,
    "end_reason": None,
}
APP_ONGOING = {**APP_RINGING, "state": "ongoing", "controls": {**NO_APP_CONTROLS, "end": True},
               "answered_at": 1727150405321}
APP_ENDED = {**APP_ONGOING, "state": "ended", "controls": NO_APP_CONTROLS, "ended_at": 1727150530456,
             "end_reason": "ended"}
APP_MISSED = {**APP_RINGING, "state": "ended", "controls": NO_APP_CONTROLS, "ended_at": 1727150425456,
              "end_reason": "missed"}


def _state(name: str, data: dict):
    return (name, "call_event-state", {"op": "state", "data": data})


def _app_call(name: str, data: dict):
    return (name, "call_event-app_call", {"op": "app_call", "data": data})


def _failure(name: str, schema: str, code: str, details: dict | None = None):
    error = {"code": code, "message": "diagnostic"}
    if details is not None:
        error["details"] = details
    return (name, schema, {"re": REQUEST_ID, "ok": False, "error": error})


POSITIVE = [
    _state("state ringing on a Mac", RINGING),
    _state("state ringing on an iPhone", {**RINGING, "controls": {**NO_CONTROLS, "reject": True}}),
    _state("state ringing number not in the contacts", {**RINGING, "display_name": None}),
    _state("state ringing without READ_CALL_LOG",
           {**RINGING, "number": None, "display_name": None, "presentation": "unknown", "sub_id": None,
            "sim_label": None}),
    _state("state ringing withheld number",
           {**RINGING, "number": None, "display_name": None, "presentation": "restricted"}),
    _state("state ringing without ANSWER_PHONE_CALLS", {**RINGING, "controls": NO_CONTROLS}),
    _state("state offhook", OFFHOOK),
    _state("state offhook over HFP with audio on the Mac", OFFHOOK_HFP),
    _state("state offhook over HFP with audio on the phone",
           {**OFFHOOK_HFP, "audio_on": "phone", "controls": {**OFFHOOK_HFP["controls"], "mute": "unavailable"}}),
    _state("state call waiting", WAITING),
    _state("state call waiting over HFP", {**WAITING, "hfp_connected": True}),
    _state("state call waiting with a known name", {**WAITING, "waiting_display_name": "Trần Thị B"}),
    _state("state outgoing", OUTGOING),
    _state("state built mid-call", {**OUTGOING, "direction": "unknown"}),
    _state("state idle missed", MISSED),
    _state("state idle rejected", {**MISSED, "end_reason": "rejected"}),
    _state("state idle answered elsewhere", {**MISSED, "end_reason": "answered_elsewhere"}),
    _state("state idle ended", {**OFFHOOK, "state": "idle", "ended_at": 1727150530456, "end_reason": "ended",
                                "controls": NO_CONTROLS}),
    _state("state outgoing ended", {**OUTGOING, "state": "idle", "ended_at": 1727150530456, "end_reason": "ended",
                                    "controls": NO_CONTROLS}),
    ("action answer on the phone", "call_event-action",
     {"op": "action", "data": {"call_id": CALL_ID, "action": "answer", "audio": "phone"}}),
    ("action answer on the Mac", "call_event-action",
     {"op": "action", "data": {"call_id": CALL_ID, "action": "answer", "audio": "mac"}}),
    ("action answer without audio", "call_event-action",
     {"op": "action", "data": {"call_id": CALL_ID, "action": "answer"}}),
    ("action reject", "call_event-action", {"op": "action", "data": {"call_id": CALL_ID, "action": "reject"}}),
    ("action end", "call_event-action", {"op": "action", "data": {"call_id": CALL_ID, "action": "end"}}),
    ("action hold", "call_event-action", {"op": "action", "data": {"call_id": CALL_ID, "action": "hold"}}),
    ("action ack", "call_event-action#ack", {"re": REQUEST_ID, "ok": True, "data": {}}),
    _failure("action not allowed", "call_event-action#ack-failure", "CALL_ACTION_NOT_ALLOWED",
             {"state": "offhook", "reason": "state"}),
    _failure("action not allowed while waiting", "call_event-action#ack-failure", "CALL_ACTION_NOT_ALLOWED",
             {"state": "ringing", "reason": "waiting"}),
    _failure("action answer from an iPhone", "call_event-action#ack-failure", "CALL_ACTION_NOT_ALLOWED",
             {"state": "ringing", "reason": "platform"}),
    _failure("action end refused by Telecom", "call_event-action#ack-failure", "CALL_ACTION_NOT_ALLOWED",
             {"state": "offhook", "reason": "system"}),
    _failure("action needs HFP", "call_event-action#ack-failure", "CALL_HFP_REQUIRED", {"action": "dtmf"}),
    _failure("action without ANSWER_PHONE_CALLS", "call_event-action#ack-failure", "PERMISSION_MISSING",
             {"permission": "android.permission.ANSWER_PHONE_CALLS"}),
    _failure("action call not found", "call_event-action#ack-failure", "CALL_NOT_FOUND"),
    _failure("action feature off", "call_event-action#ack-failure", "FEATURE_DISABLED", {}),
    _failure("action app call answer on the Mac", "call_event-action#ack-failure", "CALL_ROUTE_FAILED"),
    _failure("action app call action unavailable", "call_event-action#ack-failure", "CALL_APP_ACTION_UNAVAILABLE"),
    _app_call("app_call ringing", APP_RINGING),
    _app_call("app_call ringing tap to answer", {**APP_RINGING, "answer_mode": "tap"}),
    _app_call("app_call ringing without caller", {**APP_RINGING, "caller": None}),
    _app_call("app_call ringing without an answer intent", {**APP_RINGING, "controls": {**NO_APP_CONTROLS, "decline": True}}),
    _app_call("app_call ongoing", APP_ONGOING),
    _app_call("app_call ongoing without an end action", {**APP_ONGOING, "controls": NO_APP_CONTROLS}),
    _app_call("app_call created ongoing", {**APP_ONGOING, "answered_at": None}),
    _app_call("app_call ended", APP_ENDED),
    _app_call("app_call ended missed", APP_MISSED),
    _app_call("app_call ended declined", {**APP_MISSED, "end_reason": "declined"}),
    _app_call("app_call ended unknown", {**APP_MISSED, "end_reason": "unknown"}),
    ("log_sync first", "call_event-log_sync", {"op": "log_sync", "data": {"limit": 200}}),
    ("log_sync incremental", "call_event-log_sync", {"op": "log_sync", "data": {"cursor": CURSOR, "limit": 500}}),
    ("log_sync ack page", "call_event-log_sync#ack",
     {"re": REQUEST_ID, "ok": True, "data": {"entries": [ENTRY, WITHHELD_ENTRY], "cursor": CURSOR,
                                             "has_more": True, "reset": False}}),
    ("log_sync ack empty log", "call_event-log_sync#ack",
     {"re": REQUEST_ID, "ok": True, "data": {"entries": [], "cursor": EMPTY_LOG_CURSOR, "has_more": False,
                                             "reset": True}}),
    _failure("log_sync without READ_CALL_LOG", "call_event-log_sync#ack-failure", "PERMISSION_MISSING",
             {"permission": "android.permission.READ_CALL_LOG"}),
    _failure("log_sync limit out of range", "call_event-log_sync#ack-failure", "BAD_REQUEST"),
    ("log_new matched", "call_event-log_new", {"op": "log_new", "data": {"entry": ENTRY, "call_id": CALL_ID}}),
    ("log_new unmatched", "call_event-log_new", {"op": "log_new", "data": {"entry": WITHHELD_ENTRY, "call_id": None}}),
    ("incoming notification on an iPhone", "call-notification#incoming",
     {"title": "Nguyễn Văn A", "body": "Incoming call · SIM 1", "threadIdentifier": "calls",
      "categoryIdentifier": "HL_CALL_INCOMING", "interruptionLevel": "timeSensitive",
      "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("incoming notification on a Mac", "call-notification#incoming",
     {"identifier": CALL_ID, "title": "No Caller ID", "body": "Incoming call", "threadIdentifier": "calls",
      "categoryIdentifier": "HL_CALL_INCOMING_MAC", "interruptionLevel": "passive",
      "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("late incoming notification", "call-notification",
     {"title": "+84 90 000 01 23", "body": "Incoming call at 2:05 PM", "threadIdentifier": "calls",
      "interruptionLevel": "active", "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("incoming notification on a Mac without actions", "call-notification#incoming",
     {"identifier": CALL_ID, "title": "Nguyễn Văn A", "body": "Incoming call · SIM 1", "threadIdentifier": "calls",
      "interruptionLevel": "passive", "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("incoming notification on a Mac during a Focus", "call-notification#incoming",
     {"identifier": CALL_ID, "title": "Nguyễn Văn A", "body": "Incoming call · SIM 1", "threadIdentifier": "calls",
      "categoryIdentifier": "HL_CALL_INCOMING_MAC", "interruptionLevel": "timeSensitive", "sound": "default",
      "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("incoming notification on a Mac without actions during a Focus", "call-notification#incoming",
     {"identifier": CALL_ID, "title": "Unknown Caller", "body": "Incoming call", "threadIdentifier": "calls",
      "interruptionLevel": "timeSensitive", "sound": "default",
      "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("incoming notification on an iPhone without actions", "call-notification#incoming",
     {"title": "Nguyễn Văn A", "body": "Cuộc gọi đến · SIM 1", "threadIdentifier": "calls",
      "interruptionLevel": "timeSensitive",
      "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("late incoming notification in Vietnamese", "call-notification#incoming",
     {"title": "Nguyễn Văn A", "body": "Cuộc gọi đến lúc 14:05", "threadIdentifier": "calls",
      "interruptionLevel": "active", "userInfo": {"pair_id": PAIR_ID, "call_id": CALL_ID, "started_at": 1727150400123}}),
    ("missed notification", "call-notification#missed",
     {"identifier": f"call-missed:{PAIR_ID}:5120", "title": "Nguyễn Văn A", "body": "Missed call · 11:00 AM · SIM 1",
      "threadIdentifier": f"calls:{PAIR_ID}", "categoryIdentifier": "HL_CALL_MISSED", "sound": "default",
      "userInfo": {"pair_id": PAIR_ID, "entry_id": 5120, "call_id": CALL_ID, "number": "+84900000123", "sub_id": 1}}),
    ("missed notification without the call log", "call-notification",
     {"identifier": f"call-missed:{PAIR_ID}:{CALL_ID}", "title": "No Caller ID", "body": "Missed call · 11:00 AM",
      "threadIdentifier": f"calls:{PAIR_ID}", "sound": "default",
      "userInfo": {"pair_id": PAIR_ID, "entry_id": None, "call_id": CALL_ID, "number": None, "sub_id": None}}),
    ("missed notification from a push", "call-notification#missed",
     {"title": "Nguyễn Văn A", "body": "Cuộc gọi nhỡ · 11:00", "threadIdentifier": "calls",
      "categoryIdentifier": "HL_CALL_MISSED",
      "userInfo": {"pair_id": PAIR_ID, "entry_id": 5120, "call_id": None, "number": "+84900000123", "sub_id": 1}}),
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


S = "call_event-state"
A = "call_event-action"
L = "call_event-log_sync"
N = "call-notification"
AC = "call_event-app_call"

# (name, schema, positive sample it starts from, change).
NEGATIVE_SPECS = [
    ("state op other", S, "state ringing on a Mac", _set(["op"], "status")),
    ("state without sim_label", S, "state ringing on a Mac", _drop(["data", "sim_label"])),
    ("state extra field", S, "state ringing on a Mac", _set(["data", "number_type"], "mobile")),
    ("state call_id not v7", S, "state ringing on a Mac", _set(["data", "call_id"], PAIR_ID)),
    ("state empty display_name", S, "state ringing on a Mac", _set(["data", "display_name"], "")),
    ("state sub_id -1", S, "state ringing without ANSWER_PHONE_CALLS", _set(["data", "sub_id"], -1)),
    ("state unknown end_reason", S, "state idle missed", _set(["data", "end_reason"], "declined")),
    ("state idle without ended_at", S, "state idle missed", _set(["data", "ended_at"], None)),
    ("state idle without end_reason", S, "state idle missed", _set(["data", "end_reason"], None)),
    ("state ringing with ended_at", S, "state ringing on a Mac", _set(["data", "ended_at"], 1727150425456)),
    ("state ringing with end_reason", S, "state ringing on a Mac", _set(["data", "end_reason"], "missed")),
    ("state allowed without number", S, "state ringing number not in the contacts", _set(["data", "number"], None)),
    ("state restricted with number", S, "state ringing withheld number",
     _set(["data", "number"], "+84900000123")),
    ("state name without number", S, "state ringing withheld number", _set(["data", "display_name"], "Nguyễn Văn A")),
    ("state waiting_number without a waiting call", S, "state offhook",
     _set(["data", "waiting_number"], "+84900000456")),
    ("state waiting name without its number", S, "state call waiting with a known name",
     _set(["data", "waiting_number"], None)),
    ("state waiting while offhook", S, "state offhook", _set(["data", "waiting"], True)),
    ("state sim_label without sub_id", S, "state ringing on a Mac", _set(["data", "sub_id"], None)),
    ("state outgoing with presentation restricted", S, "state outgoing", _set(["data", "presentation"], "restricted")),
    ("state outgoing with answered_at", S, "state outgoing", _set(["data", "answered_at"], 1727150405321)),
    ("state built mid-call with answered_at", S, "state built mid-call", _set(["data", "answered_at"], 1727150405321)),
    ("state outgoing ended as missed", S, "state outgoing ended", _set(["data", "end_reason"], "missed")),
    ("state incoming offhook without answered_at", S, "state offhook", _set(["data", "answered_at"], None)),
    ("state incoming ended without answered_at", S, "state idle ended", _set(["data", "answered_at"], None)),
    ("state ringing with answered_at", S, "state ringing on a Mac", _set(["data", "answered_at"], 1727150405321)),
    ("state missed with answered_at", S, "state idle missed", _set(["data", "answered_at"], 1727150405321)),
    ("state reject while offhook", S, "state offhook",
     _set(["data", "controls"], {**NO_CONTROLS, "end": True, "reject": True})),
    ("state answer without reject", S, "state ringing on a Mac", _set(["data", "controls", "reject"], False)),
    ("state reject while waiting", S, "state call waiting", _set(["data", "controls", "reject"], True)),
    ("state end while ringing", S, "state ringing on a Mac", _set(["data", "controls", "end"], True)),
    ("state hold without HFP", S, "state offhook",
     _set(["data", "controls"], {**NO_CONTROLS, "end": True, "hold": "hfp", "dtmf": "hfp"})),
    ("state hold unavailable over HFP", S, "state offhook over HFP with audio on the phone",
     _set(["data", "controls"], {**NO_CONTROLS, "end": True})),
    ("state dtmf differs from hold", S, "state offhook over HFP with audio on the Mac",
     _set(["data", "controls", "dtmf"], "unavailable")),
    ("state mute with audio on the phone", S, "state offhook over HFP with audio on the Mac",
     _set(["data", "audio_on"], "phone")),
    ("state hold while waiting over HFP", S, "state call waiting over HFP",
     _set(["data", "controls"], {**NO_CONTROLS, "hold": "hfp", "dtmf": "hfp"})),
    ("action unknown action", A, "action reject", _set(["data", "action"], "swap")),
    ("action audio with reject", A, "action reject", _set(["data", "audio"], "phone")),
    ("action audio speaker", A, "action answer on the phone", _set(["data", "audio"], "speaker")),
    ("action without call_id", A, "action end", _drop(["data", "call_id"])),
    ("action ack with data", A + "#ack", "action ack", _set(["data"], {"state": "offhook"})),
    ("action error code of SMS", A + "#ack-failure", "action call not found",
     _set(["error", "code"], "SMS_NO_SERVICE")),
    ("action HFP error without details", A + "#ack-failure", "action needs HFP", _drop(["error", "details"])),
    ("action HFP error for answer", A + "#ack-failure", "action needs HFP", _set(["error", "details", "action"], "answer")),
    ("action permission other than ANSWER_PHONE_CALLS", A + "#ack-failure", "action without ANSWER_PHONE_CALLS",
     _set(["error", "details", "permission"], "android.permission.READ_CALL_LOG")),
    ("action not allowed without details", A + "#ack-failure", "action not allowed", _drop(["error", "details"])),
    ("action not allowed unknown reason", A + "#ack-failure", "action not allowed",
     _set(["error", "details", "reason"], "busy")),
    ("action not allowed waiting while offhook", A + "#ack-failure", "action not allowed while waiting",
     _set(["error", "details", "state"], "offhook")),
    ("action refused by Telecom while idle", A + "#ack-failure", "action end refused by Telecom",
     _set(["error", "details", "state"], "idle")),
    ("action app call unavailable code of SMS", A + "#ack-failure", "action app call action unavailable",
     _set(["error", "code"], "SMS_NO_SERVICE")),
    ("app_call op other", AC, "app_call ringing", _set(["op"], "app")),
    ("app_call without caller", AC, "app_call ringing", _drop(["data", "caller"])),
    ("app_call empty caller", AC, "app_call ringing", _set(["data", "caller"], "")),
    ("app_call caller over 128 characters", AC, "app_call ringing", _set(["data", "caller"], "A" * 129)),
    ("app_call extra field", AC, "app_call ringing", _set(["data", "number"], "+84900000123")),
    ("app_call call_id not v7", AC, "app_call ringing", _set(["data", "call_id"], PAIR_ID)),
    ("app_call package without a dot", AC, "app_call ringing", _set(["data", "app", "package"], "telegram")),
    ("app_call label over 64 characters", AC, "app_call ringing", _set(["data", "app", "label"], "T" * 65)),
    ("app_call app extra field", AC, "app_call ringing", _set(["data", "app", "icon"], "x")),
    ("app_call state offhook", AC, "app_call ongoing", _set(["data", "state"], "offhook")),
    ("app_call audio on the Mac", AC, "app_call ongoing", _set(["data", "audio"], "mac")),
    ("app_call answer_mode other", AC, "app_call ringing", _set(["data", "answer_mode"], "auto")),
    ("app_call controls reject", AC, "app_call ringing", _set(["data", "controls", "reject"], True)),
    ("app_call answer while ongoing", AC, "app_call ongoing", _set(["data", "controls", "answer"], True)),
    ("app_call decline while ended", AC, "app_call ended", _set(["data", "controls", "decline"], True)),
    ("app_call end while ringing", AC, "app_call ringing", _set(["data", "controls", "end"], True)),
    ("app_call ringing with answered_at", AC, "app_call ringing", _set(["data", "answered_at"], 1727150405321)),
    ("app_call missed with answered_at", AC, "app_call ended missed", _set(["data", "answered_at"], 1727150405321)),
    ("app_call ended without ended_at", AC, "app_call ended", _set(["data", "ended_at"], None)),
    ("app_call ended without end_reason", AC, "app_call ended", _set(["data", "end_reason"], None)),
    ("app_call ongoing with end_reason", AC, "app_call ongoing", _set(["data", "end_reason"], "ended")),
    ("app_call end_reason rejected", AC, "app_call ended", _set(["data", "end_reason"], "rejected")),
    ("log_sync limit 0", L, "log_sync first", _set(["data", "limit"], 0)),
    ("log_sync limit 501", L, "log_sync first", _set(["data", "limit"], 501)),
    ("log_sync without limit", L, "log_sync incremental", _drop(["data", "limit"])),
    ("log_sync cursor not b64u", L, "log_sync incremental", _set(["data", "cursor"], CURSOR + "=")),
    ("log_sync ack without reset", L + "#ack", "log_sync ack page", _drop(["data", "reset"])),
    ("log_sync ack 501 entries", L + "#ack", "log_sync ack empty log", _set(["data", "entries"], [ENTRY] * 501)),
    ("log_sync ack entry type unknown", L + "#ack", "log_sync ack page",
     _set(["data", "entries", 0, "type"], "answered_externally")),
    ("log_sync ack entry_id 0", L + "#ack", "log_sync ack page", _set(["data", "entries", 0, "entry_id"], 0)),
    ("log_sync ack negative duration", L + "#ack", "log_sync ack page",
     _set(["data", "entries", 0, "duration_s"], -1)),
    ("log_sync ack entry without sub_id", L + "#ack", "log_sync ack page", _drop(["data", "entries", 1, "sub_id"])),
    ("log_sync permission other than READ_CALL_LOG", L + "#ack-failure", "log_sync without READ_CALL_LOG",
     _set(["error", "details", "permission"], "android.permission.ANSWER_PHONE_CALLS")),
    ("log_sync error code of calls", L + "#ack-failure", "log_sync limit out of range",
     _set(["error", "code"], "CALL_NOT_FOUND")),
    ("log_new without call_id", "call_event-log_new", "log_new matched", _drop(["data", "call_id"])),
    ("log_new call_id not v7", "call_event-log_new", "log_new matched", _set(["data", "call_id"], PAIR_ID)),
    ("log_new entry extra field", "call_event-log_new", "log_new matched", _set(["data", "entry", "cached"], True)),
    ("incoming notification in the sms thread", N + "#incoming", "incoming notification on an iPhone",
     _set(["threadIdentifier"], "sms")),
    ("incoming notification missed category", N + "#incoming", "incoming notification on an iPhone",
     _set(["categoryIdentifier"], "HL_CALL_MISSED")),
    ("incoming notification without started_at", N + "#incoming", "incoming notification on a Mac",
     _drop(["userInfo", "started_at"])),
    ("incoming notification identifier not a call_id", N + "#incoming", "incoming notification on a Mac",
     _set(["identifier"], f"call:{CALL_ID}")),
    ("incoming notification on a Mac at the active level", N + "#incoming", "incoming notification on a Mac",
     _set(["interruptionLevel"], "active")),
    ("incoming notification with its category at the active level", N + "#incoming",
     "incoming notification on an iPhone", _set(["interruptionLevel"], "active")),
    ("late incoming notification with the Mac identifier", N + "#incoming", "late incoming notification in Vietnamese",
     _set(["identifier"], CALL_ID)),
    ("passive incoming notification on a Mac with a sound", N + "#incoming", "incoming notification on a Mac",
     _set(["sound"], "default")),
    ("incoming notification on an iPhone with a sound", N + "#incoming", "incoming notification on an iPhone",
     _set(["sound"], "default")),
    ("incoming notification on an iPhone without actions with a sound", N + "#incoming",
     "incoming notification on an iPhone without actions", _set(["sound"], "default")),
    ("late incoming notification with a sound", N + "#incoming", "late incoming notification in Vietnamese",
     _set(["sound"], "default")),
    ("incoming notification on a Mac during a Focus with another sound", N + "#incoming",
     "incoming notification on a Mac during a Focus", _set(["sound"], "ringtone")),
    ("incoming notification with a sound and no level", N + "#incoming", "incoming notification on a Mac during a Focus",
     _drop(["interruptionLevel"])),
    ("incoming notification at an unknown level", N + "#incoming", "incoming notification on an iPhone",
     _set(["interruptionLevel"], "critical")),
    ("missed notification identifier of an SMS", N + "#missed", "missed notification",
     _set(["identifier"], f"call-missed:{PAIR_ID}:sms:12847")),
    ("missed notification identifier with device_id", N + "#missed", "missed notification",
     _set(["identifier"], "call-missed:2c3d4e5f-6a7b-8c9d-8e0f-1a2b3c4d5e6f:5120")),
    ("missed notification Message without number", N + "#missed", "missed notification from a push",
     _set(["userInfo", "number"], None)),
    ("missed notification without entry_id and call_id", N + "#missed", "missed notification without the call log",
     _set(["userInfo", "call_id"], None)),
    ("missed notification thread of a thread_id", N + "#missed", "missed notification",
     _set(["threadIdentifier"], "calls:42")),
    ("missed notification userInfo without sub_id", N + "#missed", "missed notification", _drop(["userInfo", "sub_id"])),
    ("missed notification other sound", N + "#missed", "missed notification", _set(["sound"], "ringtone")),
]

NEGATIVE = [(name, schema, _variant(base, change)) for name, schema, base, change in NEGATIVE_SPECS]
