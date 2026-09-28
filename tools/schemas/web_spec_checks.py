"""Checks of the Continue Browsing schemas against the tables of 00-common-specs (0.7.1, 0.7.2, 0.10).

- web ops: every `web` row of 0.7.1 has a web-<op> schema and no web-<op> schema lacks a row.
- browser ids: the id column of the 0.7.1 browser table equals the web-active browser enum, in order.
- features.web: the `features.web.*` rows of 0.7.2 equal the fields of capability-hello feature-web.
- limits: WEB_URL_MAX (8 KiB) and WEB_TITLE_MAX (characters) of 0.10 equal url and title maxLength.
"""

from __future__ import annotations

import re
from pathlib import Path


def _section(text: str, start: str, end: str) -> str:
    if start not in text:
        raise ValueError(f"heading not found: {start}")
    return text.split(start, 1)[1].split(end, 1)[0]


def _compare(report, label: str, spec, schema) -> None:
    if spec == schema:
        report.ok("enum khớp bảng spec")
    else:
        report.fail(f"{label}: spec {spec}, schema {schema}")


def check_tables(schemas: dict, docs_dir: Path, report) -> None:
    common = (docs_dir / "00-common-specs.md").read_text(encoding="utf-8")
    types = _section(common, "### 0.7.1", "### 0.7.2")
    spec_ops = sorted(re.findall(r"^\| `web` \| `([a-z_]+)` \|", types, re.M))
    files = sorted(n.removeprefix("web-") for n in schemas if n.startswith("web-"))
    _compare(report, "web ops vs 0.7.1", spec_ops, files)

    browsers = types.split("Browser ids", 1)[1]
    spec_ids = re.findall(r"^\| [^|]+ \| `([a-z_]+)` \|", browsers, re.M)
    _compare(report, "web-active browser enum vs 0.7.1 browser table", spec_ids,
             schemas["web-active"]["$defs"]["browser"]["enum"])

    capability = _section(common, "### 0.7.2", "### 0.7.3")
    spec_fields = sorted(re.findall(r"^\| `features\.web\.([a-z_]+)` \|", capability, re.M))
    feature = schemas["capability-hello"]["$defs"]["feature-web"]
    _compare(report, "capability features.web vs 0.7.2", spec_fields, sorted(feature["properties"]))
    _compare(report, "capability features.web required vs 0.7.2", spec_fields, sorted(feature["required"]))

    constants = _section(common, "## 0.10", "## 0.11")
    url_kib = int(re.search(r"^\| `WEB_URL_MAX` \| (\d+) KiB", constants, re.M).group(1))
    title_max = int(re.search(r"^\| `WEB_TITLE_MAX` \| (\d+) characters", constants, re.M).group(1))
    data = schemas["web-active"]["properties"]["data"]["properties"]
    _compare(report, "web-active url maxLength vs WEB_URL_MAX", url_kib * 1024, data["url"]["maxLength"])
    _compare(report, "web-active title maxLength vs WEB_TITLE_MAX", title_max, data["title"]["maxLength"])
