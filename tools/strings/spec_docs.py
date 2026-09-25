"""Read the hub docs for the catalog checks: spec IDs from headings, and where a UI text is quoted.

The detailed design is bilingual (decision C20): X.md in English and X.vi.md in Vietnamese. While the docs are
being translated a lone X.md may still be Vietnamese, so a file without a .vi.md twin is classified by its share
of Vietnamese letters, the same measure tools/docs/check_bilingual_docs.py in the hub uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from catalog_rules import PLACEHOLDER, variants

VI_LETTERS = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
VI_SHARE = 0.05  # Vietnamese prose is 15-25 % such letters; English that quotes Vietnamese stays under 3 %
LEAF_ID = re.compile(r"\b([A-Z]{2,6}-\d{2})\b")
SECTION_ID = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)+)\s")
# Straight and curly quotes compare equal: the specs quote UI text with "…" and nest '…' inside it.
QUOTES = str.maketrans({"“": '"', "”": '"', "‘": '"', "’": '"', "'": '"'})


@dataclass
class Doc:
    path: Path
    lang: str  # "en" or "vi"
    text: str  # normalized with normalize()


def spec_ids(docs_dir: Path) -> set[str]:
    """Leaf function IDs (SET-01) and section numbers (0.12.1) that appear in headings of the detailed design."""
    ids: set[str] = set()
    for path in sorted(docs_dir.glob("*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                continue
            ids.update(LEAF_ID.findall(line))
            section = SECTION_ID.match(line)
            if section:
                ids.add(section.group(1))
    return ids


def vi_share(text: str) -> float:
    letters = [c for c in text.lower() if c.isalpha()]
    return sum(c in VI_LETTERS for c in letters) / len(letters) if letters else 0.0


def doc_language(path: Path, raw: str) -> str:
    if path.name.endswith(".vi.md"):
        return "vi"
    if path.with_name(path.name[:-3] + ".vi.md").is_file():
        return "en"
    return "vi" if vi_share(raw) >= VI_SHARE else "en"


def normalize(text: str) -> str:
    """One line of prose: no table breaks, blockquote markers or line wraps; one kind of quote."""
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"(?m)^\s*>\s?", " ", text)
    return re.sub(r"\s+", " ", text.translate(QUOTES))


def load_docs(dirs: list[Path]) -> list[Doc]:
    docs = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            raw = path.read_text(encoding="utf-8")
            docs.append(Doc(path, doc_language(path, raw), normalize(raw)))
    return docs


def text_pattern(text: str) -> re.Pattern:
    """Regex for a catalog text: a placeholder matches the example or <name> the spec writes in its place."""
    norm = normalize(text).strip()
    parts = re.split(r"(\{[a-z][a-z0-9_]*\})", norm)
    body = "".join(r".{1,80}?" if PLACEHOLDER.fullmatch(part) else re.escape(part) for part in parts if part)
    start = r"(?<!\w)" if norm[:1].isalnum() else ""
    end = r"(?!\w)" if norm[-1:].isalnum() else ""
    return re.compile(start + body + end)


def quoted_in(translation, corpus: str) -> bool:
    """True when some variant of the translation appears in the corpus (a final period is optional)."""
    for _, text in variants(translation):
        candidates = [text] + ([text[:-1]] if text.endswith(".") and len(text) > 1 else [])
        if any(text_pattern(candidate).search(corpus) for candidate in candidates):
            return True
    return False


def missing_from_docs(catalog: dict, docs: list[Doc]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Per language: keys whose text no doc of that language quotes, and how many such docs exist.

    A language without any doc yet (English while the specs are being translated) has no missing keys; the
    caller reports it as skipped."""
    missing: dict[str, list[str]] = {}
    doc_count: dict[str, int] = {}
    for lang in catalog.get("languages", []):
        same = [doc for doc in docs if doc.lang == lang]
        doc_count[lang] = len(same)
        corpus = "\n".join(doc.text for doc in same)
        missing[lang] = [entry["key"] for entry in catalog.get("strings", [])
                         if same and lang in entry and not quoted_in(entry[lang], corpus)]
    return missing, doc_count
