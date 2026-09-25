"""Rules of the UI string catalog (00-common-specs 0.12.1 and 0.12.5), independent of the docs.

check_catalog() returns every problem it finds instead of stopping at the first one, so one run lists all
the fixes an author has to make. tools/schemas/check_schemas.py reuses it for the catalog example in 0.12.1.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator

GROUPS = ("common", "setup", "settings", "pairing", "status", "menu", "clipboard", "sms", "call", "call_audio",
          "camera", "permission", "notification", "push", "error", "a11y", "infoplist")
# CLDR plural categories each language uses for integers; a language missing here needs "other" and CLDR names.
PLURAL_CATEGORIES = {"en": {"one", "other"}, "vi": {"other"}}
CLDR_CATEGORIES = {"zero", "one", "two", "few", "many", "other"}
PLURAL_SELECTOR = "count"  # the int argument that selects the plural variant on Android and Apple

LANGUAGE_FIELD = re.compile(r"^[a-z]{2}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
CONTROL_CHARS = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")  # a line feed is the only control character allowed
# "New style" Vietnamese tone marks sit on the second vowel of an open oa, oe, uy rhyme (hoá, khoẻ, huỷ).
# Apple writes them on the first vowel (hóa, khỏe, hủy). "qu" is a consonant, so quý and quả are correct.
NEW_STYLE_TONE = re.compile(r"(?<!q)(?:o[áàảãạéèẻẽẹ]|u[ýỳỷỹỵ])(?!\w)", re.IGNORECASE)
TERMINAL_PUNCTUATION = (".", "?", "!", ":", "…")


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(text: str) -> object:
    """json.loads that rejects an object repeating a field (json would silently keep the last value)."""

    def no_duplicates(pairs):
        fields = [name for name, _ in pairs]
        repeated = sorted({name for name in fields if fields.count(name) > 1})
        if repeated:
            raise ValueError(f"field repeated in one object: {', '.join(repeated)}")
        return dict(pairs)

    return json.loads(text, object_pairs_hook=no_duplicates)


def variants(translation) -> list[tuple[str, str]]:
    """(plural category or "", text) pairs of one translation."""
    if isinstance(translation, str):
        return [("", translation)]
    if isinstance(translation, dict):
        return [(category, text) for category, text in translation.items() if isinstance(text, str)]
    return []


def apple_style(word: str) -> str:
    """Move a new-style tone mark to the first vowel: hoá -> hóa, huỷ -> hủy, khoẻ -> khỏe."""

    def move(match: re.Match) -> str:
        first, second = match.group(0)
        base, *marks = unicodedata.normalize("NFD", second)
        return unicodedata.normalize("NFC", first + "".join(marks)) + base

    return NEW_STYLE_TONE.sub(move, word)


def new_style_words(text: str) -> list[str]:
    """Words of a Vietnamese text written with new-style tone marks."""
    return [word for word in re.findall(r"\w+", text) if NEW_STYLE_TONE.search(word)]


def check_catalog(catalog: object, schema: dict, spec_ids: set[str] | None) -> Result:
    """All catalog rules; spec_ids=None skips the check that "specs" name real headings of the docs."""
    result = Result()
    for error in sorted(Draft202012Validator(schema).iter_errors(catalog), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        result.error(f"schema: {where}: {error.message[:200]}")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("strings"), list):
        return result
    languages = [lang for lang in catalog.get("languages", []) if isinstance(lang, str)]
    entries = [entry for entry in catalog["strings"] if isinstance(entry, dict)]
    _check_keys(entries, result)
    for entry in entries:
        _check_entry(entry, languages, spec_ids, result)
    return result


def _check_keys(entries: list[dict], result: Result) -> None:
    by_key: dict[str, int] = {}
    by_resource: dict[str, str] = {}
    previous = ""
    for index, entry in enumerate(entries):
        key = entry.get("key")
        if not isinstance(key, str):
            continue
        if key in by_key:
            result.error(f"{key}: duplicate key (entries {by_key[key]} and {index})")
        by_key.setdefault(key, index)
        resource = key.replace(".", "_")
        if by_resource.get(resource, key) != key:
            result.error(f"{key}: same Android resource name {resource!r} as {by_resource[resource]}")
        by_resource.setdefault(resource, key)
        if key.split(".")[0] not in GROUPS:
            result.error(f"{key}: unknown group {key.split('.')[0]!r} (groups: {', '.join(GROUPS)})")
        if key < previous:
            result.error(f"{key}: entries must be sorted by key; it comes after {previous}")
        previous = max(previous, key)


def _check_entry(entry: dict, languages: list[str], spec_ids: set[str] | None, result: Result) -> None:
    key = entry.get("key") if isinstance(entry.get("key"), str) else "(entry without key)"
    for lang in languages:
        if lang not in entry:
            result.error(f"{key}: no {lang!r} translation")
    for name in entry:
        if LANGUAGE_FIELD.match(name) and name not in languages:
            result.error(f"{key}: translation {name!r} is not in \"languages\"")
    translations = {lang: entry[lang] for lang in languages if lang in entry}

    args = [arg for arg in entry.get("args", []) if isinstance(arg, dict)]
    names = [arg.get("name") for arg in args]
    for name in sorted({n for n in names if names.count(n) > 1}):
        result.error(f"{key}: argument {name!r} declared twice")
    declared = set(names)
    types = {arg.get("name"): arg.get("type") for arg in args}

    plural = [lang for lang, value in translations.items() if isinstance(value, dict)]
    if plural:
        _check_plural(key, translations, plural, types, result)

    for lang, value in translations.items():
        for category, text in variants(value):
            where = f"{key} [{lang}{'.' + category if category else ''}]"
            _check_text(text, where, lang, result)
            used = _placeholders(text, where, result)
            for name in sorted(used - declared):
                result.error(f"{where}: placeholder {{{name}}} is not declared in \"args\"")
            if category in ("", "other"):
                for name in sorted(declared - used):
                    result.error(f"{where}: argument {name!r} is declared but not used")

    group = key.split(".")[0]
    if group == "infoplist" and "plist_key" not in entry:
        result.error(f"{key}: group infoplist needs \"plist_key\"")
    if group != "infoplist" and "plist_key" in entry:
        result.error(f"{key}: \"plist_key\" is allowed only in group infoplist")

    if spec_ids is not None:
        for spec in entry.get("specs", []):
            if isinstance(spec, str) and spec not in spec_ids:
                result.error(f"{key}: spec {spec!r} is not a heading of docs/detailed-design")

    endings = {}
    for lang, value in translations.items():
        text = value if isinstance(value, str) else value.get("other") if isinstance(value, dict) else None
        if isinstance(text, str) and text:
            endings[lang] = text[-1] if text.endswith(TERMINAL_PUNCTUATION) else "none"
    if len(set(endings.values())) > 1:
        detail = ", ".join(f"{lang} {mark!r}" for lang, mark in endings.items())
        result.warn(f"{key}: translations end with different punctuation ({detail})")


def _check_plural(key: str, translations: dict, plural: list[str], types: dict, result: Result) -> None:
    if len(plural) != len(translations):
        plain = sorted(set(translations) - set(plural))
        result.error(f"{key}: plural in {', '.join(plural)} but plain text in {', '.join(plain)}")
    if types.get(PLURAL_SELECTOR) != "int":
        result.error(f"{key}: a plural needs an int argument named {PLURAL_SELECTOR!r} to select the variant")
    for lang in plural:
        categories = set(translations[lang])
        expected = PLURAL_CATEGORIES.get(lang)
        if expected is not None and categories != expected:
            result.error(f"{key} [{lang}]: plural categories {sorted(categories)}, CLDR needs {sorted(expected)}")
        elif expected is None and ("other" not in categories or not categories <= CLDR_CATEGORIES):
            result.error(f"{key} [{lang}]: plural categories {sorted(categories)} are not CLDR names with 'other'")


def _check_text(text: str, where: str, lang: str, result: Result) -> None:
    if not text.strip():
        result.error(f"{where}: empty text")
        return
    if text != text.strip():
        result.error(f"{where}: leading or trailing whitespace")
    if unicodedata.normalize("NFC", text) != text:
        result.error(f"{where}: not in Unicode NFC (compose the diacritics)")
    if CONTROL_CHARS.search(text):
        result.error(f"{where}: control character (only a line feed is allowed)")
    if "..." in text:
        result.error(f"{where}: three dots; write the ellipsis character \"…\"")
    if lang == "vi":
        for word in new_style_words(text):
            result.error(f"{where}: {word!r} carries the tone mark on the second vowel; write {apple_style(word)!r}")


def _placeholders(text: str, where: str, result: Result) -> set[str]:
    rest = PLACEHOLDER.sub("", text)
    if "{" in rest or "}" in rest:
        result.error(f"{where}: brace outside a {{lower_snake_case}} placeholder")
    return set(PLACEHOLDER.findall(text))
