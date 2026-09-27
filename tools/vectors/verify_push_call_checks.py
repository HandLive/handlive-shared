"""Call pushes of push-envelope.json, checked independently of the generator (CALL-01 API 1 and 4, CALL-04 API 2 and 5).

- A push only goes to an iPhone/iPad without a session, so a call_event/state carries the controls of an iOS client:
  answer = false (only a Mac answers, CALL-01 API 1 logic 4), hfp_connected = false, audio_on = phone.
- call_incoming: a ringing call, never a waiting one (CALL-01 API 4 logic 1), sent after it started.
- call_missed: a log_new entry of type missed; without the call log (flow A) a state idle with end_reason = missed,
  number = null and presentation = unknown — with READ_CALL_LOG the push comes from log_new (CALL-04 API 5 logic 2).
- Across vectors: a missed push keyed call:<call_id> replaces the incoming push of the same call (same collapse key);
  a log_new names a call that started within 5 s of the entry, with the same number (CALL-04 API 2 logic 2).
- Coverage: both reasons, both missed sources, both collapse forms, and an incoming call without the number.
"""

MATCH_WINDOW_MS = 5_000
NO_ACTIONS = {"answer": False, "reject": False, "end": False, "hold": "unavailable", "dtmf": "unavailable",
              "mute": "unavailable"}


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


def check_call(c, n: str, v: dict, body: dict) -> None:
    data = body["data"]
    if body["op"] == "state":
        c.eq(f"{n} controls of an iPhone/iPad", (data["controls"]["answer"], data["hfp_connected"], data["audio_on"]),
             (False, False, "phone"))
        if v["reason"] == "call_incoming":
            c.eq(f"{n} a ringing call, not a waiting one", (data["state"], data["waiting"], data["end_reason"]),
                 ("ringing", False, None))
            c.true(f"{n} sent after the call started", v["ts"] >= data["started_at"])
        else:
            c.eq(f"{n} missed, without the call log", (data["state"], data["end_reason"], data["number"],
                                                       data["presentation"]), ("idle", "missed", None, "unknown"))
            c.eq(f"{n} no action left", data["controls"], NO_ACTIONS)
            c.true(f"{n} sent after the call ended", data["ended_at"] is not None and v["ts"] >= data["ended_at"])
    else:
        c.eq(f"{n} a missed entry", data["entry"]["type"], "missed")
        c.true(f"{n} sent after the call", v["ts"] >= data["entry"]["ts"])


def check_coverage(c, calls: list[tuple[dict, dict]]) -> None:
    """calls = (vector, decrypted plaintext) of every call push."""
    incoming = {v["apns_headers"]["apns-collapse-id"]: body["data"] for v, body in calls
                if v["reason"] == "call_incoming" and body["op"] == "state"}
    missed = [(v, body) for v, body in calls if v["reason"] == "call_missed"]
    for v, body in missed:
        key = v["apns_headers"]["apns-collapse-id"]
        if not key.startswith("call:"):
            continue
        c.true(f"push-envelope/{v['name']} replaces the incoming push of its call", key in incoming)
        if body["op"] == "log_new" and key in incoming:
            call, entry = incoming[key], body["data"]["entry"]
            c.true(f"push-envelope/{v['name']} matches its call (5 s, same number)",
                   abs(entry["ts"] - call["started_at"]) <= MATCH_WINDOW_MS and call["direction"] == "incoming"
                   and (entry["number"] is None or call["number"] is None or entry["number"] == call["number"]))
    keys = {v["apns_headers"]["apns-collapse-id"].split(":")[0] for v, _ in missed}
    c.eq("push-envelope: call reasons", {v["reason"] for v, _ in calls}, {"call_incoming", "call_missed"})
    c.eq("push-envelope: missed call from log_new and from state", {body["op"] for _, body in missed}, {"log_new", "state"})
    c.eq("push-envelope: missed call keyed call: and calllog:", keys, {"call", "calllog"})
    c.true("push-envelope: an incoming call without the number",
           any(data["number"] is None and data["presentation"] == "unknown" for data in incoming.values()))
