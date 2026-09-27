"""Validates every message the fake Mac sends and receives against shared/schemas (JSON Schema 2020-12).

Names follow tools/schemas/check_schemas.py: "<type>-<op>" for a payload plaintext, "<type>-<op>#<def>" for a $defs
entry (the op's own ack: "sms-sync#ack", "call_event-action#ack-failure"), "ack" and "envelope" for the frames.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


class SchemaCheck:
    def __init__(self, schema_dir: Path = SCHEMA_DIR) -> None:
        schemas = {p.name.removesuffix(".schema.json"): json.loads(p.read_text(encoding="utf-8"))
                   for p in sorted(schema_dir.glob("*.schema.json"))}
        registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
        self.validators: dict[str, Draft202012Validator] = {
            name: Draft202012Validator(schema, registry=registry) for name, schema in schemas.items()}
        for name, schema in schemas.items():
            for definition in schema.get("$defs", {}):
                ref = {"$ref": f"{schema['$id']}#/$defs/{definition}"}
                self.validators[f"{name}#{definition}"] = Draft202012Validator(ref, registry=registry)

    def errors(self, schema: str, instance) -> list[str]:
        """Empty when valid; otherwise the most relevant error first."""
        validator = self.validators.get(schema)
        if validator is None:
            return [f"no schema {schema!r}"]
        errs = list(validator.iter_errors(instance))
        if not errs:
            return []
        best = best_match(errs)
        path = "/".join(str(p) for p in best.absolute_path)
        return [f"{schema}: {best.message} at /{path}"] + [f"{schema}: {e.message}" for e in errs if e is not best][:3]

    def payload_schema(self, typ: str, op: str) -> str:
        """The op's own schema when shared/schemas has one, otherwise the generic {op, data} plaintext."""
        name = f"{typ}-{op}"
        return name if name in self.validators else "payload"

    def ack_schema(self, typ: str, op: str, ok: bool) -> str:
        """The request's own ack ($defs/ack, $defs/ack-failure) when defined, otherwise the generic ack."""
        name = f"{typ}-{op}#ack" + ("" if ok else "-failure")
        return name if name in self.validators else "ack"

    def check_payload(self, typ: str, op: str, plaintext: dict) -> list[str]:
        return self.errors(self.payload_schema(typ, op), plaintext)

    def check_ack(self, typ: str, op: str, ack: dict) -> list[str]:
        # An op's own ack refs ack.schema.json#/$defs/success or /failure, so it checks the frame as well.
        return self.errors(self.ack_schema(typ, op, ack.get("ok") is True), ack)
