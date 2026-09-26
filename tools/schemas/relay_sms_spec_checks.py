"""Checks that tie the SMS, relay and push schemas to the tables of the specs and to the test vectors.

Called by check_schemas.py:
- tables: 0.7.1 (sms ops and which of them ack with data), 0.7.3 (relay control ops), 0.7.4 (relay REST
  endpoints and their bodies), 0.8.2 (relay error codes), CONN-04 API 2 (push reasons) and API 4 (APNs loc-keys,
  which must also be push.* keys of the UI string catalog shown on iOS);
- vectors: the wire messages inside shared/test-vectors (relay REST requests, pair/* plaintexts) must pass their
  schemas;
- embedded envelopes: env_b64 of POST /v1/push and hl of the APNs payload must decode to a valid envelope.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from pathlib import Path

from jsonschema.exceptions import best_match

# Relay REST endpoints of 0.7.4 → the relay-rest.schema.json $defs of their JSON bodies (none: no JSON body).
REST_BODIES = {
    ("POST", "/v1/devices"): ["devices-request", "devices-response"],
    ("POST", "/v1/auth/challenge"): ["auth-challenge-request", "auth-challenge-response"],
    ("POST", "/v1/auth/token"): ["auth-token-request", "auth-token-response"],
    ("PUT", "/v1/devices/me/push-token"): ["push-token-request"],
    ("DELETE", "/v1/devices/me?revoke_pairs=<bool>"): [],
    ("POST", "/v1/pairs"): ["pairs-request", "pairs-response"],
    ("GET", "/v1/pairs"): ["pairs-list-response"],
    ("POST", "/v1/pairs/{pair_id}/revoke"): ["pair-revoke-request"],
    ("POST", "/v1/push"): ["push-request", "push-response"],
    ("GET (WS)", "/v1/relay"): [],
}
REST_SHARED_DEFS = {"error-response", "error-code"}
# Wire messages in the test vectors: (file, field holding JSON text, schema).
VECTOR_MESSAGES = [
    ("relay-auth.json", "request", {"register": "relay-rest#devices-request", "auth": "relay-rest#auth-token-request"}),
    ("pair-handshake.json", "pairs_request", "relay-rest#pairs-request"),
    ("pair-handshake.json", "hello_plaintext", "pair-hello"),
    ("pair-handshake.json", "offer_plaintext", "pair-offer"),
    ("pair-handshake.json", "confirm_plaintext", "pair-confirm"),
    ("pair-handshake.json", "done_plaintext", "pair-done"),
]
EMBEDDED_ENVELOPE = {"relay-rest#push-request": "env_b64", "push#apns-payload": "hl"}


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def check_tables(schemas: dict, common_specs: Path, docs_dir: Path, catalog_path: Path, report) -> None:
    text = common_specs.read_text(encoding="utf-8")

    table = _section(text, "### 0.8.2", "### 0.8.3")
    spec = re.findall(r"^\| \d{3} \| `([A-Z0-9_]+)` \|", table, re.M)
    _compare(report, "relay-rest.error-code vs 0.8.2", spec, schemas["relay-rest"]["$defs"]["error-code"]["enum"])

    table = _section(text, "### 0.7.3", "### 0.7.4")
    spec = re.findall(r"^\| `([a-z_]+)` \|", table, re.M)
    files = [n.removeprefix("relay-") for n in schemas if n.startswith("relay-") and n not in ("relay-rest", "relay-wrapper")]
    _compare(report, "relay control ops vs 0.7.3", sorted(spec), sorted(files))

    table = _section(text, "### 0.7.4", "## 0.8")
    rows = re.findall(r"^\| (GET \(WS\)|GET|POST|PUT|DELETE) \| `([^`]+)` \|", table, re.M)
    _compare(report, "relay REST endpoints vs 0.7.4", sorted(rows), sorted(REST_BODIES))
    defs = set(schemas["relay-rest"]["$defs"])
    mapped = {name for names in REST_BODIES.values() for name in names}
    _compare(report, "relay-rest $defs vs the endpoint bodies", sorted(defs - REST_SHARED_DEFS), sorted(mapped))

    table = _section(text, "### 0.7.1", "### 0.7.2")
    rows = re.findall(r"^\| `sms` \| `([a-z_]+)` \| [^|]+ \| ([^|]+) \|", table, re.M)
    files = sorted(n.removeprefix("sms-") for n in schemas if n.startswith("sms-") and n not in ("sms-common", "sms-notification"))
    _compare(report, "sms ops vs 0.7.1", sorted(op for op, _ in rows), files)
    for op, ack in rows:
        has_ack = "ack" in schemas.get(f"sms-{op}", {}).get("$defs", {})
        if ("with data" in ack) and not has_ack:
            report.fail(f"sms-{op}: 0.7.1 acks with data but the schema has no $defs/ack")
        else:
            report.ok("enum khớp bảng spec")

    conn = (docs_dir / "03-connectivity.md").read_text(encoding="utf-8")
    api2 = _section(conn, "#### API 2 — `POST /v1/push`", "#### API 3")
    reasons = re.search(r"^\| `reason` \| enum\{([^}]*)\}", api2, re.M)
    spec = [r.strip(" \\") for r in reasons.group(1).split("|")] if reasons else []
    _compare(report, "push reason vs CONN-04 API 2", spec, schemas["relay-rest"]["$defs"]["push-request"]["properties"]["reason"]["enum"])

    api4 = _section(conn, "#### API 4 — APNs HTTP/2", "#### Query")
    spec = re.findall(r"^\| `[a-z_]+` \| `(push\.[a-z_]+)`", api4, re.M)
    loc_keys = schemas["push"]["$defs"]["apns-payload"]["properties"]["aps"]["properties"]["alert"]["properties"]["loc-key"]["enum"]
    _compare(report, "APNs loc-key vs CONN-04 API 4", sorted(spec), sorted(loc_keys))
    catalog = {e["key"]: e for e in json.loads(catalog_path.read_text(encoding="utf-8"))["strings"]}
    for key in loc_keys:
        if key in catalog and "ios" in catalog[key]["platforms"]:
            report.ok("loc-key có trong catalog")
        else:
            report.fail(f"APNs loc-key {key}: not an iOS key of strings/ui-strings.json")


def _compare(report, label: str, spec, schema) -> None:
    if list(spec) == list(schema):
        report.ok("enum khớp bảng spec")
    else:
        report.fail(f"{label}: spec {list(spec)}, schema {list(schema)}")


def validate_embedded_envelope(schema_name: str, instance, validators, report, label: str) -> None:
    """env_b64 / hl carry b64 of the UTF-8 JSON envelope encrypted with K_push (CONN-04 step 5b)."""
    field = EMBEDDED_ENVELOPE.get(schema_name)
    if field is None or not isinstance(instance, dict) or field not in instance:
        return
    try:
        envelope = json.loads(base64.b64decode(instance[field], validate=True))
    except (ValueError, binascii.Error) as exc:
        report.fail(f"{label}: {field} is not b64 of a JSON envelope: {exc}")
        return
    error = best_match(validators["envelope"].iter_errors(envelope))
    if error is None:
        report.ok("envelope trong env_b64/hl")
    else:
        report.fail(f"{label}: {field} → envelope: {error.message}")


def validate_vector_messages(vectors_dir: Path, validators, report) -> None:
    for file, field, schema in VECTOR_MESSAGES:
        path = vectors_dir / file
        if not path.is_file():
            report.fail(f"{file}: missing")
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        found = 0
        for vector in doc.get("vectors", []):
            if field not in vector:
                continue
            name = schema[vector["kind"]] if isinstance(schema, dict) else schema
            instance = json.loads(vector[field])
            error = best_match(validators[name].iter_errors(instance))
            label = f"{file} / {vector['name']} / {field} [{name}]"
            if error is None:
                report.ok("tin trong test vector")
                validate_embedded_envelope(name, instance, validators, report, label)
            else:
                report.fail(f"{label}: {error.message}")
            found += 1
        if found:
            print(f"  PASS {file}: {found} × {field}")
        else:
            report.fail(f"{file}: no vector carries {field}")
