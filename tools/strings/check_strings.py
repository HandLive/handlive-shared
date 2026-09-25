"""Check the UI string catalog strings/ui-strings.json (00-common-specs 0.12.5, decision C20).

Run from the handlive-shared root with the tools venv:
  tools/.venv/bin/python tools/strings/check_strings.py              # catalog rules; exit 1 on any error
  tools/.venv/bin/python tools/strings/check_strings.py --docs       # also warn when a text is not in the specs
  tools/.venv/bin/python tools/strings/check_strings.py --self-test  # tests of the checker itself, no docs needed

Errors (exit 1):
  1. the catalog is valid against strings/ui-strings.schema.json (JSON Schema 2020-12), no field repeated;
  2. keys are unique, also after "." -> "_" (Android resource names), and entries are sorted by key;
  3. every language of "languages" is in every entry, no other language is;
  4. placeholders {name} are declared in "args" and form the same set in every translation; no stray brace;
  5. plurals use the CLDR categories of each language (en: one + other, vi: other) in every translation and
     have an int argument "count";
  6. texts are non-empty, without leading or trailing whitespace, NFC, without control characters, and use
     "…" instead of "...";
  7. vi texts carry Apple-style tone marks (hóa, xóa, hủy, tùy — never hoá, xoá, huỷ, tuỳ);
  8. "plist_key" is present exactly in group infoplist;
  9. every "specs" ID is a leaf function or a 0.x section heading of docs/detailed-design.
Warnings: translations ending with different punctuation; an article, coordinating conjunction or preposition of
four or fewer letters capitalized inside an English title-style text; with --docs, a vi text no Vietnamese spec quotes or
an en text no English spec quotes (docs/detailed-design and docs/design-system).

The docs are the hub's docs/detailed-design: ../docs/detailed-design from this repository root, or
HANDLIVE_DOCS_DIR, or the directory given to --docs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the repository
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_rules  # noqa: E402
import spec_docs  # noqa: E402

SHARED_ROOT = Path(__file__).resolve().parents[2]
CATALOG = SHARED_ROOT / "strings" / "ui-strings.json"
SCHEMA = SHARED_ROOT / "strings" / "ui-strings.schema.json"


def default_docs_dir() -> Path:
    return Path(os.environ.get("HANDLIVE_DOCS_DIR") or SHARED_ROOT.parent / "docs" / "detailed-design")


def load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def run(catalog_path: Path, docs_dir: Path, with_docs: bool) -> int:
    rel = catalog_path.relative_to(SHARED_ROOT) if catalog_path.is_relative_to(SHARED_ROOT) else catalog_path
    if not (docs_dir / "00-common-specs.md").is_file():
        print(f"check_strings: no 00-common-specs.md in {docs_dir}; point HANDLIVE_DOCS_DIR (or --docs DIR) "
              "at the hub's docs/detailed-design")
        return 2
    try:
        catalog = catalog_rules.load_json(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"check_strings: cannot read {rel}: {exc}")
        return 1
    result = catalog_rules.check_catalog(catalog, load_schema(), spec_docs.spec_ids(docs_dir))
    count = len(catalog.get("strings", [])) if isinstance(catalog, dict) else 0
    languages = ", ".join(catalog.get("languages", [])) if isinstance(catalog, dict) else "?"
    print(f"== {rel}: {count} strings, languages {languages}")
    for message in result.errors:
        print(f"  FAIL {message}")
    for message in result.warnings:
        print(f"  WARN {message}")
    if with_docs and not result.errors:
        report_docs(catalog, docs_dir, result)
    print(f"== {count} strings, {len(result.errors)} errors, {len(result.warnings)} warnings")
    if result.errors:
        print("FAILED")
        return 1
    print("OK")
    return 0


def report_docs(catalog: dict, docs_dir: Path, result: catalog_rules.Result) -> None:
    dirs = [docs_dir, docs_dir.parent / "design-system"]
    docs = spec_docs.load_docs(dirs)
    missing, doc_count = spec_docs.missing_from_docs(catalog, docs)
    print(f"== --docs: texts quoted in {', '.join(str(d) for d in dirs if d.is_dir())} (warnings only)")
    names = {"en": "English", "vi": "Vietnamese"}
    for lang, keys in missing.items():
        name = names.get(lang, lang)
        if not doc_count[lang]:
            print(f"  SKIP {lang}: no {name} spec yet")
            continue
        total = sum(lang in entry for entry in catalog["strings"])
        print(f"  {lang}: {total - len(keys)} of {total} texts found in {doc_count[lang]} {name} docs")
        for key in keys:
            result.warn(f"{key} [{lang}]: not quoted in the {name} specs")
            print(f"  WARN {key} [{lang}]: not quoted in the {name} specs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--catalog", type=Path, default=CATALOG, help="catalog to check (default: %(default)s)")
    parser.add_argument("--docs", nargs="?", const="", metavar="DIR",
                        help="also warn about texts the specs do not quote; DIR = docs/detailed-design")
    parser.add_argument("--self-test", action="store_true", help="run the checker's own tests")
    args = parser.parse_args(argv)
    if args.self_test:
        import self_test  # noqa: PLC0415 - only needed here
        return self_test.main(load_schema())
    docs_dir = Path(args.docs) if args.docs else default_docs_dir()
    return run(args.catalog.resolve(), docs_dir, with_docs=args.docs is not None)


if __name__ == "__main__":
    sys.exit(main())
