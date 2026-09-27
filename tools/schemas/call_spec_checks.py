"""Checks that tie the call schemas (call_event-*, call-notification) to the tables of the specs.

Called by check_schemas.py with the hub's docs/detailed-design:
- 00-common-specs: the call_event ops of 0.7.1 (one call_event-<op> file each, $defs/ack for the ops that ack),
  the details.reason values of CALL_ACTION_NOT_ALLOWED (0.8.1) and the call_log_entry.type CHECK (0.9.3);
- 06-call-control.md (English, canonical): the data fields of call_event/state and of its controls object
  (CALL-01 API 1), of call_event/action with its action enum and error codes in check order (CALL-02 API 1), of the
  shared entry object with its type enum, of call_event/log_sync (request, ack data, error codes) and
  call_event/log_new (CALL-04 API 1–2), and the userInfo fields of the call notifications (CALL-01 API 6,
  CALL-04 API 4).
call_event/hfp_status is specified with call audio (AUDIO-02 API 3), not in 0.7 or CALL-03, so it has no schema yet.
"""

from __future__ import annotations

import re
from pathlib import Path

CALL_DOC = "06-call-control.md"
# Ops of 0.7.1 whose fields another function group specifies: no schema until that group is implemented.
DEFERRED_OPS = {"hfp_status": "specified in AUDIO-02 API 3 (call audio)"}
TICKED = re.compile(r"`([^`]+)`")


def _section(text: str, start: str, end: str) -> str:
    if start not in text:
        raise ValueError(f"heading not found: {start}")
    return text.split(start, 1)[1].split(end, 1)[0]


def _table_after(text: str, marker: str) -> list[list[str]]:
    """Rows (cells without the | borders) of the first markdown table after marker, header and rule excluded."""
    if marker not in text:
        raise ValueError(f"marker not found: {marker}")
    rows, started = [], False
    for line in text.split(marker, 1)[1].splitlines():
        if line.startswith("|"):
            started = True
            # A cell may hold an escaped pipe (enum{a\| b}); only the unescaped ones separate cells.
            rows.append([cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]])
        elif started:
            break
    return rows[2:]


def _first_ticked(rows: list[list[str]]) -> list[str]:
    return [m.group(1) for row in rows if (m := TICKED.match(row[0]))]


def _enum_in(cell: str) -> list[str]:
    match = re.search(r"enum\{([^}]*)\}", cell)
    return [value.strip(" \\") for value in match.group(1).split("|")] if match else []


def _properties(schema: dict, *path: str) -> dict:
    node = schema
    for part in path:
        node = node[part]
    return node


def check_tables(schemas: dict, docs_dir: Path, report) -> None:
    common = (docs_dir / "00-common-specs.md").read_text(encoding="utf-8")
    call = (docs_dir / CALL_DOC).read_text(encoding="utf-8")

    # 0.7.1: every call_event op has a call_event-<op> schema (except the deferred ones); ops with an ack have $defs/ack.
    table = _section(common, "### 0.7.1", "### 0.7.2")
    rows = re.findall(r"^\| `call_event` \| `([a-z_]+)` \| [^|]+ \| ([^|]+) \|", table, re.M)
    spec_ops = sorted(op for op, _ in rows if op not in DEFERRED_OPS)
    files = sorted(n.removeprefix("call_event-") for n in schemas if n.startswith("call_event-") and n != "call_event-common")
    _compare(report, "call_event ops vs 0.7.1 (hfp_status: AUDIO-02)", spec_ops, files)
    for op, ack in rows:
        if op in DEFERRED_OPS:
            continue
        has_ack = "ack" in schemas.get(f"call_event-{op}", {}).get("$defs", {})
        if ack.strip().startswith("Yes") != has_ack:
            report.fail(f"call_event-{op}: 0.7.1 ack column {ack.strip()!r} but $defs/ack {'present' if has_ack else 'missing'}")
        else:
            report.ok("enum khớp bảng spec")

    # 0.8.1: details.reason of CALL_ACTION_NOT_ALLOWED.
    row = re.search(r"^\| `CALL_ACTION_NOT_ALLOWED` \|.*$", common, re.M).group(0)
    spec = TICKED.findall(row.split("`details.reason`", 1)[1].split("|", 1)[0])
    schema = schemas["call_event-action"]["$defs"]["not-allowed-details"]["properties"]["reason"]["enum"]
    _compare(report, "CALL_ACTION_NOT_ALLOWED details.reason vs 0.8.1", spec, schema)

    # 0.9.3: call_log_entry.type CHECK.
    table = _section(common, "CREATE TABLE call_log_entry", ");")
    spec = re.findall(r"'([a-z]+)'", re.search(r"CHECK \(type IN \(([^)]*)\)\)", table).group(1))
    entry = schemas["call_event-common"]["$defs"]
    _compare(report, "call_event-common call-type vs 0.9.3 call_log_entry.type", spec, entry["call-type"]["enum"])

    # CALL-01 API 1: call_event/state data and controls.
    api = _section(call, "#### API 1 — `WS call_event/state`", "#### API 2")
    state = schemas["call_event-state"]["$defs"]
    rows = _table_after(api, "**Request (`data`):**")
    _compare(report, "call_event/state data vs CALL-01 API 1", _first_ticked(rows), list(state["state-data"]["properties"]))
    required = [name for name, row in zip(_first_ticked(rows), rows) if row[2] == "Yes"]
    _compare(report, "call_event/state required vs CALL-01 API 1", required, state["state-data"]["required"])
    rows = _table_after(api, "The `controls` object:")
    _compare(report, "call_event/state controls vs CALL-01 API 1", _first_ticked(rows), list(state["controls"]["properties"]))
    for name, row in zip(_first_ticked(rows), rows):
        values = _enum_in(row[1])
        if values:
            _compare(report, f"controls.{name} vs CALL-01 API 1", values, state["hfp-control"]["enum"])

    # CALL-02 API 1: call_event/action data, action enum, error codes in check order (INTERNAL last).
    api = _section(call, "#### API 1 — `WS call_event/action`", "#### API 2")
    action = schemas["call_event-action"]
    rows = _table_after(api, "**Request (`data`):**")
    data = action["properties"]["data"]
    _compare(report, "call_event/action data vs CALL-02 API 1", _first_ticked(rows), list(data["properties"]))
    _compare(report, "call_event/action action enum vs CALL-02 API 1", _enum_in(rows[1][1]), action["$defs"]["action"]["enum"])
    _compare(report, "call_event/action audio enum vs CALL-02 API 1", _enum_in(rows[2][1]), data["properties"]["audio"]["enum"])
    codes = _first_ticked(_table_after(api, "Errors (`ack.error.code`), in check order:"))
    _compare(report, "call_event/action error codes vs CALL-02 API 1", codes,
             action["$defs"]["error"]["properties"]["code"]["enum"])

    # CALL-04: the shared entry object, log_sync, log_new.
    rows = _table_after(call, "**Shared data object** — `entry`")
    _compare(report, "entry vs CALL-04 shared data object", _first_ticked(rows), list(entry["entry"]["properties"]))
    _compare(report, "entry type vs CALL-04 shared data object", _enum_in(rows[3][1]), entry["call-type"]["enum"])
    api = _section(call, "#### API 1 — `WS call_event/log_sync`", "#### API 2")
    log_sync = schemas["call_event-log_sync"]
    rows = _table_after(api, "**Request (`data`):**")
    _compare(report, "call_event/log_sync data vs CALL-04 API 1", _first_ticked(rows),
             list(log_sync["properties"]["data"]["properties"]))
    rows = _table_after(api, "**Response (`ack.data`):**")
    _compare(report, "call_event/log_sync ack data vs CALL-04 API 1", _first_ticked(rows),
             list(log_sync["$defs"]["ack-data"]["properties"]))
    errors = re.search(r"Errors \(`ack\.error\.code`\): (.*?)\n\n", api, re.S).group(1)
    codes = [code for code in TICKED.findall(errors) if re.fullmatch(r"[A-Z_]+", code)]
    _compare(report, "call_event/log_sync error codes vs CALL-04 API 1", codes,
             log_sync["$defs"]["error"]["properties"]["code"]["enum"])
    api = _section(call, "#### API 2 — `WS call_event/log_new`", "#### API 3")
    rows = _table_after(api, "**Request (`data`):**")
    _compare(report, "call_event/log_new data vs CALL-04 API 2", _first_ticked(rows),
             list(schemas["call_event-log_new"]["properties"]["data"]["properties"]))

    # Notification userInfo (CALL-01 API 6, CALL-04 API 4).
    notification = schemas["call-notification"]["$defs"]
    for label, start, end, kind in (("CALL-01 API 6", "#### API 6 — iOS banner", "#### API 7", "incoming"),
                                    ("CALL-04 API 4", "#### API 4 — Missed-call notification", "#### API 5", "missed")):
        api = _section(call, start, end)
        row = re.search(r"^\| `userInfo` \| `\{([^}]*)\}`", api, re.M).group(1)
        spec = [name.strip() for name in row.split(",")]
        _compare(report, f"{kind} notification userInfo vs {label}", spec,
                 list(notification[kind]["properties"]["userInfo"]["properties"]))


def _compare(report, label: str, spec, schema) -> None:
    if list(spec) == list(schema):
        report.ok("enum khớp bảng spec")
    else:
        report.fail(f"{label}: spec {list(spec)}, schema {list(schema)}")
