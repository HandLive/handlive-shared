"""Kiểm JSON Schema trong shared/schemas/ với ví dụ của tài liệu thiết kế.

Chạy: tools/.venv/bin/python tools/schemas/check_schemas.py
1. Mọi schema hợp lệ theo metaschema draft 2020-12, $id khớp tên file, mọi $ref phân giải được;
   enum mã lỗi, mã đóng WebSocket và type khớp bảng 0.8.1, 0.8.3 và 0.7.1; op sms, op điều khiển relay,
   endpoint REST, mã lỗi relay, reason và loc-key push khớp 0.7.1, 0.7.3, 0.7.4, 0.8.2, CONN-04
   (relay_sms_spec_checks.py).
2. Ví dụ JSON trong 00-common-specs.md (bắt buộc, mọi khối ```json phải được phân loại) và ví dụ trong
   01–08 (khối ```json, thân JSON trong khối ```http, inline) có schema thì phải qua schema tương ứng:
   envelope/ack/session/capability/sms/clipboard, bọc định tuyến và tin điều khiển relay, thân REST relay,
   thân push; env_b64/hl phải giải ra một envelope hợp lệ.
3. Mẫu dương tự viết phải qua; mẫu âm phải bị từ chối.
4. Ví dụ catalog chuỗi giao diện (khối ```jsonc có "strings" trong 00-common-specs, mục 0.12.1) qua
   strings/ui-strings.schema.json và các quy tắc của tools/strings/catalog_rules.py (trừ thứ tự khóa).
5. Tin trên dây trong shared/test-vectors (yêu cầu relay-auth, pairs_request) qua schema relay REST.
Thoát 0 khi mọi mục xanh.
"""

from __future__ import annotations

import json
import re
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

sys.dont_write_bytecode = True  # không để lại __pycache__ trong kho
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doc_examples  # noqa: E402
import relay_sms_spec_checks  # noqa: E402
import sample_messages  # noqa: E402
import sample_messages_relay  # noqa: E402
import sample_messages_sms  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strings"))
import catalog_rules  # noqa: E402
import spec_docs  # noqa: E402

SHARED_ROOT = Path(__file__).resolve().parents[2]  # gốc kho shared/
SCHEMA_DIR = SHARED_ROOT / "schemas"
# Tài liệu thiết kế nằm ở kho hub (thư mục cha của shared/ trong workspace); ghi đè bằng HANDLIVE_DOCS_DIR.
DOCS_DIR = Path(os.environ.get("HANDLIVE_DOCS_DIR") or SHARED_ROOT.parent / "docs" / "detailed-design")
COMMON_SPECS = DOCS_DIR / "00-common-specs.md"
if not COMMON_SPECS.is_file():
    sys.exit(f"Không thấy {COMMON_SPECS}: đặt HANDLIVE_DOCS_DIR trỏ tới docs/detailed-design của kho hub")
ID_BASE = "https://handlive.app/schemas/v1/"
VECTORS_DIR = SHARED_ROOT / "test-vectors"
CATALOG = SHARED_ROOT / "strings" / "ui-strings.json"
SAMPLE_MODULES = (sample_messages, sample_messages_sms, sample_messages_relay)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.counts: dict[str, int] = {}

    def ok(self, bucket: str) -> None:
        self.counts[bucket] = self.counts.get(bucket, 0) + 1

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"  FAIL {message}")


def load_schemas(report: Report) -> tuple[dict[str, dict], Registry]:
    schemas: dict[str, dict] = {}
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        name = path.name.removesuffix(".schema.json")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # SchemaError
            report.fail(f"{path.name}: không hợp lệ theo metaschema: {exc}")
            continue
        if schema.get("$id") != ID_BASE + path.name:
            report.fail(f"{path.name}: $id = {schema.get('$id')!r}, cần {ID_BASE + path.name!r}")
            continue
        schemas[name] = schema
        report.ok("schema hợp lệ metaschema")
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas.values()
    )
    return schemas, registry


def check_refs(schemas: dict[str, dict], registry: Registry, report: Report) -> None:
    for name, schema in schemas.items():
        resolver = registry.resolver(base_uri=schema["$id"])
        for ref in _collect_refs(schema):
            try:
                resolver.lookup(ref)
                report.ok("$ref phân giải được")
            except Exception as exc:
                report.fail(f"{name}: $ref {ref!r} không phân giải được: {exc}")


def _collect_refs(node) -> list[str]:
    if isinstance(node, dict):
        refs = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return refs + [r for v in node.values() for r in _collect_refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in _collect_refs(v)]
    return []


def check_enums_match_spec(schemas: dict[str, dict], report: Report) -> None:
    text = COMMON_SPECS.read_text(encoding="utf-8")
    table = text.split("### 0.8.1", 1)[1].split("### 0.8.2", 1)[0]
    spec_codes = re.findall(r"^\| `([A-Z0-9_]+)` \|", table, re.M)
    schema_codes = schemas["error"]["$defs"]["code"]["enum"]
    if spec_codes == schema_codes:
        report.ok("enum khớp bảng spec")
    else:
        report.fail(f"error.code lệch 0.8.1: thiếu {set(spec_codes) - set(schema_codes)}, "
                    f"thừa {set(schema_codes) - set(spec_codes)}")
    table = text.split("### 0.8.3", 1)[1].split("\n## ", 1)[0]
    spec_close = [int(code) for code in re.findall(r"^\| (\d{4}) \|", table, re.M)]
    schema_close = schemas["common"]["$defs"]["ws-close-code"]["enum"]
    if spec_close == schema_close:
        report.ok("enum khớp bảng spec")
    else:
        report.fail(f"common.ws-close-code lệch 0.8.3: spec {spec_close}, schema {schema_close}")
    section = text.split("### 0.7.1", 1)[1].split("### 0.7.2", 1)[0]
    spec_types = set(re.findall(r"^\| `([a-z_]+)` \|", section, re.M))
    schema_types = set(schemas["envelope"]["$defs"]["type"]["enum"])
    if spec_types == schema_types:
        report.ok("enum khớp bảng spec")
    else:
        report.fail(f"envelope.type lệch 0.7.1: spec {sorted(spec_types)}, schema {sorted(schema_types)}")
    relay_sms_spec_checks.check_tables(schemas, COMMON_SPECS, DOCS_DIR, CATALOG, report)


def make_validators(schemas: dict[str, dict], registry: Registry) -> dict[str, Draft202012Validator]:
    validators = {n: Draft202012Validator(s, registry=registry) for n, s in schemas.items()}
    # Mỗi $defs có validator "<schema>#<def>": ack của op có data riêng ("sms-sync#ack"), thân REST relay
    # ("relay-rest#push-request"), thân push ("push#apns-payload").
    for name, schema in schemas.items():
        for definition in schema.get("$defs", {}):
            ref = {"$ref": schema["$id"] + "#/$defs/" + definition}
            validators[f"{name}#{definition}"] = Draft202012Validator(ref, registry=registry)
    return validators


def validate_docs(validators, report: Report) -> None:
    doc_files = sorted(DOCS_DIR.glob("0*.md"))
    for path in doc_files:
        strict = path == COMMON_SPECS
        for ex in doc_examples.extract_examples(path):
            _check_example(ex, strict, validators, report)


def _check_example(ex, strict: bool, validators, report: Report) -> None:
    known = doc_examples.KNOWN_SPEC_ISSUES.get((ex.file, ex.line))
    if ex.parse_error:
        if known:
            report.ok("known spec issue (đúng như ghi nhận)")
            print(f"  KNOWN {ex.where}: {known}")
        else:
            report.fail(f"{ex.where}: khối ```json không parse được: {ex.parse_error}")
        return
    schema = doc_examples.classify(ex, strict_payload=strict, known=set(validators))
    if schema is None:
        if strict and ex.source == "block":
            report.fail(f"{ex.where}: khối ```json trong 00-common-specs không phân loại được")
        else:
            report.ok("ngoài phạm vi S0.2 (bỏ qua)")
        return
    try:
        instance = doc_examples.substitute_placeholders(ex.obj, ex.substitutions)
    except ValueError as exc:
        report.fail(f"{ex.where}: {exc}")
        return
    _validate_one(f"{ex.where} [{schema}]", schema, instance, validators, report, known,
                  bucket="ví dụ 00-common-specs" if strict else "ví dụ 01–08",
                  subs=ex.substitutions)
    relay_sms_spec_checks.validate_embedded_envelope(schema, instance, validators, report, ex.where)
    if schema == "envelope":
        inner = doc_examples.decode_handshake_payload(instance)
        if inner is not None:
            inner_schema = f"session-{inner.get('op')}"
            subs: list[str] = []
            inner = doc_examples.substitute_placeholders(inner, subs)
            _validate_one(f"{ex.where} [payload đã giải b64 -> {inner_schema}]", inner_schema, inner,
                          validators, report, known=None, bucket="payload bắt tay giải từ envelope", subs=subs)


def _validate_one(label, schema, instance, validators, report, known, bucket, subs) -> None:
    if schema not in validators:
        report.fail(f"{label}: không có schema {schema!r}")
        return
    error = best_match(validators[schema].iter_errors(instance))
    if error is None and not known:
        report.ok(bucket)
        note = f" (placeholder: {'; '.join(subs)})" if subs else ""
        print(f"  PASS {label}{note}")
    elif error is None and known:
        report.fail(f"{label}: đã qua schema nhưng còn trong KNOWN_SPEC_ISSUES — xóa mục đó")
    elif known:
        report.ok("known spec issue (đúng như ghi nhận)")
        print(f"  KNOWN {label}: {known}")
    else:
        path = "/".join(str(p) for p in error.absolute_path) or "(gốc)"
        report.fail(f"{label}: {path}: {error.message}")


def validate_samples(validators, report: Report) -> None:
    positive = [sample for module in SAMPLE_MODULES for sample in module.POSITIVE]
    negative = [sample for module in SAMPLE_MODULES for sample in module.NEGATIVE]
    for name, schema, instance in positive:
        error = best_match(validators[schema].iter_errors(instance))
        if error is None:
            report.ok("mẫu dương tự viết")
            relay_sms_spec_checks.validate_embedded_envelope(schema, instance, validators, report, name)
        else:
            report.fail(f"mẫu dương '{name}' bị từ chối: {error.message}")
    for name, schema, instance in negative:
        error = best_match(validators[schema].iter_errors(instance))
        if error is None:
            report.fail(f"mẫu âm '{name}' lại được chấp nhận")
        else:
            report.ok("mẫu âm bị từ chối")
            print(f"  REJECT {name}: {error.message[:110]}")


def validate_catalog_examples(report: Report) -> None:
    """Khối ```jsonc dạng catalog (có "languages" và "strings") trong 00-common-specs phải qua mọi quy tắc catalog."""
    schema = json.loads((SHARED_ROOT / "strings" / "ui-strings.schema.json").read_text(encoding="utf-8"))
    ids = spec_docs.spec_ids(DOCS_DIR)
    found = 0
    for line, block in _jsonc_blocks(COMMON_SPECS):
        where = f"{COMMON_SPECS.name}:{line}"
        try:
            obj = catalog_rules.load_json(block)
        except ValueError as exc:
            report.fail(f"{where}: khối ```jsonc không parse được: {exc}")
            continue
        if not (isinstance(obj, dict) and "strings" in obj and "languages" in obj):
            report.ok("khối jsonc không phải catalog (bỏ qua)")
            continue
        found += 1
        result = catalog_rules.check_catalog(obj, schema, ids, require_sorted=False)
        for message in result.errors:
            report.fail(f"{where} [ui-strings]: {message}")
        if not result.errors:
            report.ok("ví dụ catalog chuỗi giao diện")
            print(f"  PASS {where} [ui-strings] ({len(obj['strings'])} mục)")
    if not found:
        report.fail(f"{COMMON_SPECS.name}: không thấy ví dụ catalog (khối ```jsonc có \"strings\", mục 0.12.1)")


def _jsonc_blocks(path: Path) -> list[tuple[int, str]]:
    """(dòng đầu nội dung, nội dung) của mỗi khối ```jsonc; bỏ dòng chú thích // đứng riêng."""
    blocks, current, start = [], None, 0
    for no, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if current is None:
            if text.strip() == "```jsonc":
                current, start = [], no + 1
        elif text.strip().startswith("```"):
            blocks.append((start, "\n".join(current)))
            current = None
        elif not text.strip().startswith("//"):
            current.append(text)
    return blocks


def main() -> int:
    report = Report()
    print("== 1. Metaschema, $id, $ref, enum khớp spec")
    schemas, registry = load_schemas(report)
    check_refs(schemas, registry, report)
    check_enums_match_spec(schemas, report)
    validators = make_validators(schemas, registry)
    print("== 2. Ví dụ trong docs/detailed-design")
    validate_docs(validators, report)
    print("== 3. Mẫu tự viết")
    validate_samples(validators, report)
    print("== 4. Ví dụ catalog chuỗi giao diện (0.12.1)")
    validate_catalog_examples(report)
    print("== 5. Tin trên dây trong test-vectors")
    relay_sms_spec_checks.validate_vector_messages(VECTORS_DIR, validators, report)
    print("== Tổng kết")
    for bucket, count in report.counts.items():
        print(f"  {bucket}: {count}")
    if report.failures:
        print(f"  THẤT BẠI: {len(report.failures)}")
        return 1
    print("  XANH: mọi kiểm tra đạt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
