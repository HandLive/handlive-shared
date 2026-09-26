"""Hand-written samples for the relay (wrapper, control ops, REST bodies) and push schemas.

Same shape as sample_messages.py: POSITIVE samples must pass, each NEGATIVE sample changes one thing in a positive
sample and must be rejected because of that change.
"""

from __future__ import annotations

import base64
import copy
import json

B64U_16 = base64.urlsafe_b64encode(bytes(range(16))).decode().rstrip("=")
B64U_32 = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
B64U_64 = base64.urlsafe_b64encode(bytes(range(64))).decode().rstrip("=")
UUID_V7 = "0192f4b2-5c6d-7e8f-9a0b-1c2d3e4f5a6b"
PAIR_ID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
DEVICE_C = "5b1f8c2e-9a4d-8e6f-a1b2-c3d4e5f60718"
DEVICE_S = "8c7d6e5f-4a3b-8c2d-9e1f-0a1b2c3d4e5f"
CALL_ID = "0192f3f0-6a1b-7c2d-8e3f-4a5b6c7d8e90"
CIPHERTEXT = base64.b64encode(bytes(range(58))).decode()
ENVELOPE = {"v": 1, "type": "sms", "id": UUID_V7, "ts": 1727151200000, "payload": CIPHERTEXT}
PAIR_ENVELOPE = {**ENVELOPE, "type": "pair"}
ENV_B64 = base64.b64encode(json.dumps(ENVELOPE, separators=(",", ":")).encode()).decode()
ATTESTATION = base64.urlsafe_b64encode(b"HLPAIR1" + bytes(range(120))).decode().rstrip("=")
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI1YjFmOGMyZS05YTRkLThlNmYtYTFiMi1jM2Q0ZTVmNjA3MTgifQ.c2ln"
APNS_TOKEN = "4f1c2e" + "0" * 58 + "a9"

POSITIVE = [
    ("wrapper to", "relay-wrapper", {"to": DEVICE_S, "env": ENVELOPE}),
    ("wrapper from", "relay-wrapper", {"from": DEVICE_C, "env": ENVELOPE}),
    ("presence", "relay-presence", {"op": "presence", "pair_id": PAIR_ID, "peer_device_id": DEVICE_S,
                                    "online": False}),
    ("relay error with to", "relay-error", {"op": "error", "code": "NOT_CONNECTED", "message": "Peer offline",
                                            "to": DEVICE_S}),
    ("relay error rendezvous", "relay-error", {"op": "error", "code": "BAD_REQUEST", "message": "Rendezvous full"}),
    ("rv_join", "relay-rv_join", {"op": "rv_join", "rv_id": B64U_16}),
    ("rv_joined", "relay-rv_joined", {"op": "rv_joined", "rv_id": B64U_16, "peer_present": False}),
    ("rv_msg", "relay-rv_msg", {"op": "rv_msg", "rv_id": B64U_16, "env": PAIR_ENVELOPE}),
    ("pair_revoked", "relay-pair_revoked", {"op": "pair_revoked", "pair_id": PAIR_ID, "by": DEVICE_C}),
    ("POST /v1/devices", "relay-rest#devices-request",
     {"device_id": DEVICE_C, "platform": "ipados", "app_version": "1.0.0 (100)", "ik_sig_pub": B64U_32,
      "ts": 1727151100000, "sig": B64U_64}),
    ("POST /v1/devices 201", "relay-rest#devices-response", {"device_id": DEVICE_C, "created_at": 1727151100420}),
    ("POST /v1/auth/challenge", "relay-rest#auth-challenge-request", {"device_id": DEVICE_C}),
    ("POST /v1/auth/challenge 200", "relay-rest#auth-challenge-response",
     {"challenge": B64U_32, "expires_at": 1727151160000}),
    ("POST /v1/auth/token", "relay-rest#auth-token-request",
     {"device_id": DEVICE_C, "challenge": B64U_32, "sig": B64U_64}),
    ("POST /v1/auth/token 200", "relay-rest#auth-token-response", {"access_token": JWT, "expires_in": 900}),
    ("PUT push-token apns", "relay-rest#push-token-request",
     {"provider": "apns_sandbox", "token": APNS_TOKEN, "topic": "app.handlive.ios"}),
    ("PUT push-token fcm", "relay-rest#push-token-request",
     {"provider": "fcm", "token": "dQw4w9WgXcQ:APA91bH-example_token"}),
    ("POST /v1/pairs", "relay-rest#pairs-request",
     {"pair_id": PAIR_ID, "device_a": DEVICE_S, "device_b": DEVICE_C, "created_at": 1727150003210,
      "attestation": ATTESTATION, "sig_a": B64U_64, "sig_b": B64U_64}),
    ("POST /v1/pairs 201", "relay-rest#pairs-response", {"pair_id": PAIR_ID, "created_at": 1727150003210}),
    ("GET /v1/pairs", "relay-rest#pairs-list-response",
     {"pairs": [{"pair_id": PAIR_ID, "peer_device_id": DEVICE_S, "peer_platform": "android",
                 "created_at": 1727150003210, "revoked_at": 1727160000000, "peer_online": False}]}),
    ("POST revoke", "relay-rest#pair-revoke-request", {"reason": "lost_device"}),
    ("POST /v1/push alert", "relay-rest#push-request",
     {"pair_id": PAIR_ID, "to": DEVICE_C, "kind": "alert", "reason": "sms_new", "env_b64": ENV_B64,
      "collapse_key": "sms:12847", "ttl_s": 86400}),
    ("POST /v1/push incoming call", "relay-rest#push-request",
     {"pair_id": PAIR_ID, "to": DEVICE_C, "kind": "alert", "reason": "call_incoming", "env_b64": ENV_B64,
      "collapse_key": f"call:{CALL_ID}", "ttl_s": 30}),
    ("POST /v1/push missed call from the call log", "relay-rest#push-request",
     {"pair_id": PAIR_ID, "to": DEVICE_C, "kind": "alert", "reason": "call_missed", "env_b64": ENV_B64,
      "collapse_key": "calllog:5120", "ttl_s": 86400}),
    ("POST /v1/push wake", "relay-rest#push-request",
     {"pair_id": PAIR_ID, "to": DEVICE_S, "kind": "wake", "reason": "user_open"}),
    ("POST /v1/push wake with a collapse key", "relay-rest#push-request",
     {"pair_id": PAIR_ID, "to": DEVICE_S, "kind": "wake", "reason": "sms_send", "collapse_key": "wake",
      "ttl_s": 60}),
    ("POST /v1/push 202", "relay-rest#push-response", {"accepted": True}),
    ("relay error body", "relay-rest#error-response",
     {"error": {"code": "PUSH_TOKEN_MISSING", "message": "Target has no push token"}}),
    ("FCM data", "push#fcm-data", {"t": "wake", "p": PAIR_ID, "r": "call_action"}),
    ("FCM request", "push#fcm-request",
     {"message": {"token": "dQw4w9WgXcQ:APA91bH-example_token",
                  "data": {"t": "wake", "p": PAIR_ID, "r": "sms_send"},
                  "android": {"priority": "HIGH", "ttl": "60s", "collapse_key": "wake"}}}),
    ("FCM response", "push#fcm-response", {"name": "projects/handlive/messages/0:1727151200000%abc"}),
    ("APNs SMS", "push#apns-payload",
     {"aps": {"alert": {"loc-key": "push.sms_new"}, "mutable-content": 1, "sound": "default", "thread-id": "sms",
              "interruption-level": "active"}, "p": PAIR_ID, "hl": ENV_B64}),
    ("APNs incoming call", "push#apns-payload",
     {"aps": {"alert": {"loc-key": "push.call_incoming"}, "mutable-content": 1, "sound": "default",
              "thread-id": "calls", "interruption-level": "time-sensitive"}, "p": PAIR_ID, "hl": ENV_B64}),
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


NEGATIVE_SPECS = [
    ("wrapper with to and from", "relay-wrapper", "wrapper to", _set(["from"], DEVICE_C)),
    ("wrapper to a pair_id", "relay-wrapper", "wrapper to", _set(["to"], PAIR_ID)),
    ("wrapper without env", "relay-wrapper", "wrapper from", _drop(["env"])),
    ("wrapper env without payload", "relay-wrapper", "wrapper to", _drop(["env", "payload"])),
    ("presence online as text", "relay-presence", "presence", _set(["online"], "false")),
    ("presence in a data object", "relay-presence", "presence",
     lambda m: m.update({"data": {"pair_id": m.pop("pair_id")}})),
    ("relay error HTTP-only code", "relay-error", "relay error with to", _set(["code"], "TOKEN_EXPIRED")),
    ("relay error without message", "relay-error", "relay error with to", _drop(["message"])),
    ("relay error BAD_REQUEST echoing to", "relay-error", "relay error with to", _set(["code"], "BAD_REQUEST")),
    ("rv_join rv_id 32 bytes", "relay-rv_join", "rv_join", _set(["rv_id"], B64U_32)),
    ("rv_join rv_id not canonical", "relay-rv_join", "rv_join", _set(["rv_id"], B64U_16[:-1] + "B")),
    ("rv_joined without peer_present", "relay-rv_joined", "rv_joined", _drop(["peer_present"])),
    ("rv_msg carrying an sms envelope", "relay-rv_msg", "rv_msg", _set(["env", "type"], "sms")),
    ("pair_revoked by a pair_id", "relay-pair_revoked", "pair_revoked", _set(["by"], PAIR_ID)),
    ("POST /v1/devices sig 32 bytes", "relay-rest#devices-request", "POST /v1/devices", _set(["sig"], B64U_32)),
    ("POST /v1/devices unknown platform", "relay-rest#devices-request", "POST /v1/devices",
     _set(["platform"], "watchos")),
    ("POST /v1/devices app_version 33", "relay-rest#devices-request", "POST /v1/devices",
     _set(["app_version"], "1" * 33)),
    ("POST /v1/devices device_id v4", "relay-rest#devices-request", "POST /v1/devices",
     _set(["device_id"], PAIR_ID)),
    ("POST /v1/auth/challenge extra field", "relay-rest#auth-challenge-request", "POST /v1/auth/challenge",
     _set(["platform"], "ios")),
    ("challenge 16 bytes", "relay-rest#auth-challenge-response", "POST /v1/auth/challenge 200",
     _set(["challenge"], B64U_16)),
    ("token request without sig", "relay-rest#auth-token-request", "POST /v1/auth/token", _drop(["sig"])),
    ("token expires_in 3600", "relay-rest#auth-token-response", "POST /v1/auth/token 200",
     _set(["expires_in"], 3600)),
    ("token not a JWS", "relay-rest#auth-token-response", "POST /v1/auth/token 200", _set(["access_token"], "abc")),
    ("push-token apns without topic", "relay-rest#push-token-request", "PUT push-token apns", _drop(["topic"])),
    ("push-token apns token not hex", "relay-rest#push-token-request", "PUT push-token apns",
     _set(["token"], "4F1C2E")),
    ("push-token fcm with topic", "relay-rest#push-token-request", "PUT push-token fcm",
     _set(["topic"], "app.handlive.ios")),
    ("push-token unknown provider", "relay-rest#push-token-request", "PUT push-token fcm",
     _set(["provider"], "hms")),
    ("pairs attestation without HLPAIR1", "relay-rest#pairs-request", "POST /v1/pairs",
     _set(["attestation"], base64.urlsafe_b64encode(b"HLPAIR2" + bytes(120)).decode().rstrip("="))),
    ("pairs attestation 126 bytes", "relay-rest#pairs-request", "POST /v1/pairs",
     _set(["attestation"], base64.urlsafe_b64encode(b"HLPAIR1" + bytes(119)).decode().rstrip("="))),
    ("pairs without sig_b", "relay-rest#pairs-request", "POST /v1/pairs", _drop(["sig_b"])),
    ("pairs list without revoked_at", "relay-rest#pairs-list-response", "GET /v1/pairs",
     _drop(["pairs", 0, "revoked_at"])),
    ("revoke reason limit", "relay-rest#pair-revoke-request", "POST revoke", _set(["reason"], "limit")),
    ("push alert without env_b64", "relay-rest#push-request", "POST /v1/push alert", _drop(["env_b64"])),
    ("push wake with env_b64", "relay-rest#push-request", "POST /v1/push wake", _set(["env_b64"], ENV_B64)),
    ("push wake with an alert reason", "relay-rest#push-request", "POST /v1/push wake",
     _set(["reason"], "sms_new")),
    ("push alert with a wake reason", "relay-rest#push-request", "POST /v1/push alert",
     _set(["reason"], "sms_send")),
    ("push env_b64 over 3000", "relay-rest#push-request", "POST /v1/push alert", _set(["env_b64"], "AAAA" * 751)),
    ("push collapse_key over 64", "relay-rest#push-request", "POST /v1/push wake with a collapse key",
     _set(["collapse_key"], "x" * 65)),
    ("push collapse_key not printable ASCII", "relay-rest#push-request", "POST /v1/push wake with a collapse key",
     _set(["collapse_key"], "đánh thức")),
    ("push collapse_key with a control character", "relay-rest#push-request",
     "POST /v1/push wake with a collapse key", _set(["collapse_key"], "wake\tup")),
    ("push SMS collapse_key with a doubled prefix", "relay-rest#push-request", "POST /v1/push alert",
     _set(["collapse_key"], "sms:sms:12847")),
    ("push SMS collapse_key per thread", "relay-rest#push-request", "POST /v1/push alert",
     _set(["collapse_key"], "sms:42:12847")),
    ("push incoming call collapse_key from the call log", "relay-rest#push-request", "POST /v1/push incoming call",
     _set(["collapse_key"], "calllog:5120")),
    ("push missed call collapse_key of an SMS", "relay-rest#push-request",
     "POST /v1/push missed call from the call log", _set(["collapse_key"], "sms:12847")),
    ("push ttl_s over 86,400", "relay-rest#push-request", "POST /v1/push alert", _set(["ttl_s"], 86401)),
    ("push ttl_s negative", "relay-rest#push-request", "POST /v1/push incoming call", _set(["ttl_s"], -1)),
    ("push response accepted false", "relay-rest#push-response", "POST /v1/push 202", _set(["accepted"], False)),
    ("relay error body with 0.8.1 code", "relay-rest#error-response", "relay error body",
     _set(["error", "code"], "SMS_NO_SERVICE")),
    ("relay error body with details", "relay-rest#error-response", "relay error body",
     _set(["error", "details"], {})),
    ("FCM data with content", "push#fcm-data", "FCM data", _set(["body"], "Hello")),
    ("FCM data alert reason", "push#fcm-data", "FCM data", _set(["r"], "sms_new")),
    ("FCM request normal priority", "push#fcm-request", "FCM request",
     _set(["message", "android", "priority"], "NORMAL")),
    ("FCM request ttl over 60 s", "push#fcm-request", "FCM request", _set(["message", "android", "ttl"], "86400s")),
    ("FCM request collapse_key not wake", "push#fcm-request", "FCM request",
     _set(["message", "android", "collapse_key"], "sms:12847")),
    ("FCM request without collapse_key", "push#fcm-request", "FCM request",
     _drop(["message", "android", "collapse_key"])),
    ("FCM request with a notification block", "push#fcm-request", "FCM request",
     _set(["message", "notification"], {"title": "HandLive"})),
    ("APNs alert with a title", "push#apns-payload", "APNs SMS", _set(["aps", "alert", "title"], "HandLive")),
    ("APNs alert with text", "push#apns-payload", "APNs SMS", _set(["aps", "alert", "body"], "New SMS message")),
    ("APNs unknown loc-key", "push#apns-payload", "APNs SMS", _set(["aps", "alert", "loc-key"], "push.generic")),
    ("APNs SMS time-sensitive", "push#apns-payload", "APNs SMS",
     _set(["aps", "interruption-level"], "time-sensitive")),
    ("APNs incoming call active", "push#apns-payload", "APNs incoming call",
     _set(["aps", "interruption-level"], "active")),
    ("APNs call in an SMS thread", "push#apns-payload", "APNs incoming call", _set(["aps", "thread-id"], "sms")),
    ("APNs SMS in the calls thread", "push#apns-payload", "APNs SMS", _set(["aps", "thread-id"], "calls")),
    ("APNs SMS thread per conversation", "push#apns-payload", "APNs SMS", _set(["aps", "thread-id"], "sms:42")),
    ("APNs without mutable-content", "push#apns-payload", "APNs SMS", _drop(["aps", "mutable-content"])),
    ("APNs without hl", "push#apns-payload", "APNs SMS", _drop(["hl"])),
]

NEGATIVE = [(name, schema, _variant(base, change)) for name, schema, base, change in NEGATIVE_SPECS]
