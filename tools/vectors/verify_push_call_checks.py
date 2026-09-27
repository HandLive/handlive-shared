"""Push reason and collapse key of a push plaintext, re-derived on the checking side (CONN-04 step 3 and 5b, SMS-02 API 2,
CALL-01 API 4, CALL-04 API 5).
"""


def push_reason(typ: str, body: dict) -> str | None:
    """The push reason the phone uses for a plaintext (CONN-04 step 3), None when it would not push it."""
    op, data = body.get("op"), body.get("data", {})
    if (typ, op) == ("sms", "new"):
        return "sms_new"
    if (typ, op) == ("call_event", "state"):
        if data.get("state") == "ringing":
            return "call_incoming"
        if data.get("state") == "idle" and data.get("end_reason") == "missed":
            return "call_missed"
    if (typ, op) == ("call_event", "log_new") and data.get("entry", {}).get("type") == "missed":
        return "call_missed"
    return None


def collapse_key(typ: str, body: dict) -> str:
    """SMS: the message_key (already sms:<_id>); a call: call:<call_id>, or calllog:<entry_id> when unknown."""
    data = body["data"]
    if typ == "sms":
        return data["message"]["message_key"]
    return f"call:{data['call_id']}" if data.get("call_id") else f"calllog:{data['entry']['entry_id']}"
