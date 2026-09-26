"""Trích ví dụ JSON từ tài liệu thiết kế, thay placeholder và phân loại theo schema.

Quy tắc (ghi lại trong tools/schemas/README.md):
- Khối ```json: thử parse cả khối; không được thì parse từng dòng khác rỗng.
  Dòng không parse được là lỗi tài liệu (phải nằm trong KNOWN_SPEC_ISSUES).
- Khối ```http: mỗi dòng bắt đầu bằng "{" là thân JSON của yêu cầu/phản hồi (relay REST).
- Inline code `{"...}`: chỉ nhận khi parse được; inline không phải JSON là ký hiệu,
  không phải ví dụ, nên bỏ qua.
- Placeholder = chuỗi dạng "<...>", chuỗi chứa "…", hoặc đúng "...". Thay theo TÊN
  KHÓA chứa nó (PLACEHOLDER_BY_KEY); khóa không có quy tắc -> lỗi, không bỏ qua.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# JSON envelope (0.5.1) làm giá trị thay cho env_b64/hl: b64 chuẩn của UTF-8 JSON {v, type, id, ts, payload}.
ENVELOPE_B64 = base64.b64encode(json.dumps(
    {"v": 1, "type": "sms", "id": "01920000-0000-7000-8000-000000000000", "ts": 1727150000000,
     "payload": base64.b64encode(bytes(40)).decode()}, separators=(",", ":")).encode()).decode()

# Giá trị thay cho placeholder, chọn theo tên khóa. Mỗi giá trị hợp lệ theo kiểu 0.3.
PLACEHOLDER_BY_KEY = {
    "id": "01920000-0000-7000-8000-000000000000",  # uuid-v7
    "re": "01920000-0000-7000-8000-000000000000",  # uuid-v7 (id của yêu cầu)
    "pair_id": "00000000-0000-4000-8000-000000000000",  # uuid-v4
    "device_id": "00000000-0000-8000-8000-000000000000",  # uuid-v8
    "payload": base64.b64encode(bytes(40)).decode(),  # b64 có padding: nonce(24)+tag(16)
    "eph": base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),  # b64u 32 byte
    "nonce": base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),
    "mac": base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),
    # Relay REST and push bodies (CONN-03, CONN-04, PAIR-01 API 8).
    "sig": base64.urlsafe_b64encode(bytes(64)).decode().rstrip("="),  # Ed25519, b64u 64 byte
    "sig_a": base64.urlsafe_b64encode(bytes(64)).decode().rstrip("="),
    "sig_b": base64.urlsafe_b64encode(bytes(64)).decode().rstrip("="),
    "attestation": base64.urlsafe_b64encode(b"HLPAIR1" + bytes(120)).decode().rstrip("="),  # 127 byte (0.6.2)
    "access_token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIwIn0.c2lnbmF0dXJl",  # JWS dạng gọn
    "token": "00" * 32,  # token APNs dạng hex (cũng là chuỗi token FCM hợp lệ)
    "env_b64": ENVELOPE_B64,  # b64 của JSON envelope mã hóa bằng K_push
    "hl": ENVELOPE_B64,
    "prk_check": base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),  # b64u 32 byte (PAIR-01 API 4–5)
    "by": "00000000-0000-8000-8000-000000000000",  # device_id (uuid-v8) của pair_revoked
    "code": "BAD_REQUEST",  # mã lỗi có trong cả 0.8.1 và 0.8.2
    "message": "diagnostic",  # chuỗi chẩn đoán tiếng Anh, chỉ để ghi log (0.12.4)
}

# Ví dụ trong tài liệu biết là sai so với đặc tả (spec tự mâu thuẫn). Khóa: (file, dòng).
# Không sửa docs/ ở thẻ S0.2; đề xuất sửa nằm trong báo cáo phase-00-S0.2.md.
KNOWN_SPEC_ISSUES: dict[tuple[str, int], str] = {}

HEADING_TYPE_OP = re.compile(r"WS (session|capability|sms|clipboard|pair|ping)/([a-z_]+)")
HEADING_TYPE_ONLY = re.compile(r"`(session|capability|sms|clipboard|pair|ping)` op")
PLACEHOLDER = re.compile(r"^<[^<>]+>$")
SCOPED_TYPES = ("session", "capability", "sms", "clipboard", "pair", "ping")

# Thân JSON không phải payload envelope: (mẫu tiêu đề mục, điều kiện trên đối tượng, schema).
BODY_RULES = [
    (re.compile(r"`POST /v1/devices`"), lambda o: "sig" in o, "relay-rest#devices-request"),
    (re.compile(r"`POST /v1/devices`"), lambda o: "created_at" in o, "relay-rest#devices-response"),
    (re.compile(r"`POST /v1/auth/challenge`"), lambda o: set(o) == {"device_id"}, "relay-rest#auth-challenge-request"),
    (re.compile(r"`POST /v1/auth/challenge`"), lambda o: "challenge" in o, "relay-rest#auth-challenge-response"),
    (re.compile(r"`POST /v1/auth/token`"), lambda o: "sig" in o, "relay-rest#auth-token-request"),
    (re.compile(r"`POST /v1/auth/token`"), lambda o: "access_token" in o, "relay-rest#auth-token-response"),
    (re.compile(r"`PUT /v1/devices/me/push-token`"), lambda o: "provider" in o, "relay-rest#push-token-request"),
    (re.compile(r"`POST /v1/pairs`"), lambda o: "attestation" in o, "relay-rest#pairs-request"),
    (re.compile(r"`POST /v1/pairs`"), lambda o: set(o) == {"pair_id", "created_at"}, "relay-rest#pairs-response"),
    (re.compile(r"`GET /v1/pairs`"), lambda o: "pairs" in o, "relay-rest#pairs-list-response"),
    (re.compile(r"`POST /v1/pairs/\{pair_id\}/revoke`"), lambda o: "reason" in o, "relay-rest#pair-revoke-request"),
    (re.compile(r"`POST /v1/push`"), lambda o: "kind" in o, "relay-rest#push-request"),
    (re.compile(r"`POST /v1/push`"), lambda o: set(o) == {"accepted"}, "relay-rest#push-response"),
    (re.compile(r"FCM HTTP v1"), lambda o: "message" in o, "push#fcm-request"),
    (re.compile(r"FCM HTTP v1"), lambda o: set(o) == {"name"}, "push#fcm-response"),
    (re.compile(r"APNs HTTP/2"), lambda o: "aps" in o, "push#apns-payload"),
    # Nội dung thông báo SMS (SMS-02 API 4): nhận theo categoryIdentifier HL_SMS…, vì tiêu đề mục khác nhau giữa hai bản ngôn ngữ.
    (re.compile(r""), lambda o: str(o.get("categoryIdentifier", "")).startswith("HL_SMS"), "sms-notification"),
]


@dataclass
class Example:
    file: str
    line: int
    heading: str
    source: str  # "block" | "inline"
    obj: object = None
    parse_error: str | None = None
    substitutions: list[str] = field(default_factory=list)

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


def _is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.match(value)) or "…" in value or value == "..."


def substitute_placeholders(obj, subs: list[str], key: str | None = None):
    """Thay placeholder đệ quy theo tên khóa; ghi lại từng lần thay vào subs."""
    if isinstance(obj, dict):
        return {k: substitute_placeholders(v, subs, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_placeholders(v, subs, key) for v in obj]
    if isinstance(obj, str) and _is_placeholder(obj):
        if key not in PLACEHOLDER_BY_KEY:
            raise ValueError(f"placeholder {obj!r} ở khóa {key!r} không có quy tắc thay")
        subs.append(f"{key}: {obj!r} -> {PLACEHOLDER_BY_KEY[key]!r}")
        return PLACEHOLDER_BY_KEY[key]
    return obj


def extract_examples(path: Path) -> list[Example]:
    """Mọi đối tượng JSON trong khối ```json và inline code của một file markdown."""
    examples: list[Example] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    heading, in_block, block_start, block = "", False, 0, []
    for no, text in enumerate(lines, start=1):
        if in_block:
            if text.strip().startswith("```"):
                if in_block == "http":
                    examples.extend(_http_bodies(path.name, heading, block))
                else:
                    examples.extend(_block_examples(path.name, heading, block_start, block))
                in_block = False
            else:
                block.append((no, text))
            continue
        if text.split("\n", 1)[0].strip() == "```json":
            in_block, block_start, block = True, no, []
            continue
        if text.strip() == "```http":
            in_block, block_start, block = "http", no, []
            continue
        if text.startswith("#"):
            heading = text
        for span in re.findall(r"`(\{\"[^`]*\})`", text):
            try:
                examples.append(Example(path.name, no, heading, "inline", json.loads(span)))
            except json.JSONDecodeError:
                pass  # ký hiệu kiểu {"op":"<tên>", ...}, không phải ví dụ
    return examples


def _http_bodies(file: str, heading: str, block) -> list[Example]:
    """Thân JSON trong khối ```http: mỗi dòng bắt đầu bằng "{" là một thân."""
    out = []
    for no, text in block:
        if not text.lstrip().startswith("{"):
            continue
        try:
            out.append(Example(file, no, heading, "http", json.loads(text)))
        except json.JSONDecodeError as exc:
            out.append(Example(file, no, heading, "http", parse_error=str(exc)))
    return out


def _block_examples(file: str, heading: str, start: int, block) -> list[Example]:
    try:
        return [Example(file, start + 1, heading, "block", json.loads("\n".join(t for _, t in block)))]
    except json.JSONDecodeError:
        pass
    out = []
    for no, text in block:
        if not text.strip():
            continue
        try:
            out.append(Example(file, no, heading, "block", json.loads(text)))
        except json.JSONDecodeError as exc:
            out.append(Example(file, no, heading, "block", parse_error=str(exc)))
    return out


def classify(ex: Example, strict_payload: bool, known: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Tên schema cần kiểm (tên file bỏ .schema.json, '<file>#<def>' cho một $defs) hoặc None nếu ngoài phạm vi.

    known = tên các validator có sẵn; schema chưa có thì bỏ qua (trừ 00-common-specs).
    strict_payload=True (00-common-specs): {op, data} không phân loại được thì kiểm bằng payload.schema.
    """
    obj = ex.obj
    if not isinstance(obj, dict):
        return None
    keys = set(obj)
    scoped_type, scoped_op = _heading_scope(ex.heading)
    if "v" in obj and "type" in obj:
        return "envelope"
    if keys == {"error"} and "relay-rest#error-response" in known:
        return "relay-rest#error-response"  # lỗi relay REST (0.8.2)
    if "env" in obj and ("to" in obj or "from" in obj) and "op" not in obj:
        return "relay-wrapper"
    if "re" in obj and "ok" in obj:
        ack = f"{scoped_type}-{scoped_op}#ack"
        if scoped_type and scoped_op and obj.get("ok") is True and ack in known:
            return ack
        if scoped_type == "session" and scoped_op == "rekey" and obj.get("ok") is True:
            return "session-rekey#ack"
        return "ack"
    if "op" in obj:
        if "data" not in obj and f"relay-{obj['op']}" in known:
            return f"relay-{obj['op']}"  # tin điều khiển relay (0.7.3)
        if scoped_type and (scoped_op is None or scoped_op == obj["op"]):
            name = f"{scoped_type}-{obj['op']}"
            if name in known or not known:
                return name
        if strict_payload:
            return "payload"
        return None
    for heading, matches, schema in BODY_RULES:
        if heading.search(ex.heading) and matches(obj) and schema in known:
            return schema
    return None


def _heading_scope(heading: str) -> tuple[str | None, str | None]:
    m = HEADING_TYPE_OP.search(heading)
    if m:
        return m.group(1), m.group(2)
    m = HEADING_TYPE_ONLY.search(heading)
    if m:
        return m.group(1), None
    return None, None


def decode_handshake_payload(envelope: dict):
    """Envelope session mang b64 của JSON chưa mã hóa (0.5.1): trả plaintext đã parse, hoặc None."""
    if envelope.get("type") != "session":
        return None
    try:
        return json.loads(base64.b64decode(envelope["payload"], validate=True))
    except (ValueError, KeyError, TypeError):
        return None
