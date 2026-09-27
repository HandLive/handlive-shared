"""The call plaintexts of push-envelope.json (CALL-01 API 1 and 4, CALL-04 API 2 and 5), on the generator side.

A push always goes to an iPhone/iPad without a session, so a call_event/state carries the controls of an iOS client:
answer = false (only a Mac may answer, CALL-01 API 1 logic 4), hfp_connected = false, audio_on = phone.

Cases (pair 2, whose client is the iPhone of relay-auth.json):
- call_incoming: the ringing call of the CALL-01 example (number, name, the SIM label of a two-SIM phone), and a
  ringing call whose number is unknown because the phone lacks READ_CALL_LOG (number = null, presentation = unknown,
  the ringing SIM not determined: sub_id = sim_label = null);
- call_missed from the call log (CALL-04 API 5): the log_new of the CALL-04 example, matched with the first call, so its
  collapse_key call:<call_id> replaces that call's incoming notification; and a missed entry no context matched
  (call_id = null), collapse_key calllog:<entry_id>;
- call_missed without the call log (flow A): the second call ends as missed, sent as a call_event/state with
  end_reason = missed under the same collapse_key as its incoming push.
"""

from push_sms_truncation import uuid7

IOS_CONTROLS = {"answer": False, "reject": True, "end": False, "hold": "unavailable", "dtmf": "unavailable",
                "mute": "unavailable"}
NO_CONTROLS = {**IOS_CONTROLS, "reject": False}

FIRST_CALL_ID = "0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90"  # the call of the CALL-01 and CALL-04 examples
SECOND_CALL_STARTED = 1727150600123
SECOND_CALL_ID = uuid7(SECOND_CALL_STARTED, "call without number")


def _state(call_id: str, started_at: int, **fields) -> dict:
    data = {"call_id": call_id, "direction": "incoming", "state": "ringing", "waiting": False,
            "number": "+84900000123", "display_name": "Nguyễn Văn A", "presentation": "allowed", "sub_id": 1,
            "sim_label": "SIM 1", "waiting_number": None, "waiting_display_name": None, "started_at": started_at,
            "answered_at": None, "ended_at": None, "end_reason": None, "controls": IOS_CONTROLS,
            "hfp_connected": False, "audio_on": "phone"}
    data.update(fields)
    return {"op": "state", "data": data}


FIRST_CALL_RINGING = _state(FIRST_CALL_ID, 1727150400123)
SECOND_CALL_UNKNOWN = {"number": None, "display_name": None, "presentation": "unknown", "sub_id": None,
                       "sim_label": None}
SECOND_CALL_RINGING = _state(SECOND_CALL_ID, SECOND_CALL_STARTED, **SECOND_CALL_UNKNOWN)
SECOND_CALL_MISSED = _state(SECOND_CALL_ID, SECOND_CALL_STARTED, **SECOND_CALL_UNKNOWN, state="idle",
                            ended_at=1727150625456, end_reason="missed", controls=NO_CONTROLS)
FIRST_CALL_LOG_NEW = {"op": "log_new", "data": {
    "entry": {"entry_id": 5120, "number": "+84900000123", "display_name": "Nguyễn Văn A", "type": "missed",
              "ts": 1727150400123, "duration_s": 0, "sub_id": 1},
    "call_id": FIRST_CALL_ID}}
UNMATCHED_LOG_NEW = {"op": "log_new", "data": {
    "entry": {"entry_id": 5121, "number": "+84900000789", "display_name": None, "type": "missed",
              "ts": 1727150700000, "duration_s": 0, "sub_id": None},
    "call_id": None}}


def _envelope(name: str, ts: int, plaintext: dict, reason: str, collapse_key: str, ttl_s: int) -> tuple:
    """A spec tuple of build_push_relay_vectors.ENVELOPES; the envelope id is a UUIDv7 of its ts."""
    return (name, "call_event", uuid7(ts, f"push envelope {name}"), ts, plaintext, reason, collapse_key, ttl_s,
            "calls")


# The first ringing call keeps the id and ts it has had since the first push vectors.
FIRST_CALL_ENVELOPE = ("pair 2 / call_event/state ringing", "call_event", "0192f3f0-6a2c-7d3e-9f40-5a6b7c8d9eaf",
                       1727150400400, FIRST_CALL_RINGING, "call_incoming", f"call:{FIRST_CALL_ID}", 30, "calls")
CALL_ENVELOPES = [
    _envelope("pair 2 / call_event/state ringing without the caller's number", 1727150600400, SECOND_CALL_RINGING,
              "call_incoming", f"call:{SECOND_CALL_ID}", 30),
    _envelope("pair 2 / call_event/log_new missed call", 1727150426500, FIRST_CALL_LOG_NEW, "call_missed",
              f"call:{FIRST_CALL_ID}", 86_400),
    _envelope("pair 2 / call_event/log_new missed call without a matching call", 1727150730900, UNMATCHED_LOG_NEW,
              "call_missed", "calllog:5121", 86_400),
    _envelope("pair 2 / call_event/state missed without the call log", 1727150625600, SECOND_CALL_MISSED,
              "call_missed", f"call:{SECOND_CALL_ID}", 86_400),
]
