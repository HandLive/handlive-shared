"""Hand-written samples for the Continue Browsing schemas (web-active, web-inactive, capability features.web).

POSITIVE samples use real values (no placeholders) and must pass; each NEGATIVE sample changes one thing in a
positive sample and must be rejected because of exactly that change. Same shape as sample_messages.py:
(name, schema, instance).
"""

from __future__ import annotations

import copy

from sample_messages import CAPABILITY_DATA

PAGE_ID = "0192f4a0-1b2c-7d3e-8f40-5a6b7c8d9e0f"
PAIR_ID = "7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d"  # a uuid v4, never a valid page_id
ACTIVE = {"page_id": PAGE_ID, "url": "https://en.wikipedia.org/wiki/Handoff#History", "title": "Handoff - Wikipedia",
          "browser": "chrome", "observed_at": 1727150400123}
# The longest URL WEB_URL_MAX allows when every character is ASCII (8192 bytes of UTF-8).
LONGEST_URL = "https://example.com/" + "a" * (8192 - len("https://example.com/"))
WEB_ON = {"enabled": True, "send": True, "receive": True}


def _active(name: str, data: dict):
    return (name, "web-active", {"op": "active", "data": data})


def _capability(name: str, schema: str, web: dict):
    data = copy.deepcopy(CAPABILITY_DATA)
    data["features"]["web"] = web
    return (name, schema, {"op": schema.removeprefix("capability-"), "data": data})


POSITIVE = [
    _active("web/active from Chrome on Android", ACTIVE),
    _active("web/active without a title", {k: v for k, v in ACTIVE.items() if k != "title"}),
    _active("web/active over http with a port and a query",
            {**ACTIVE, "url": "http://192.168.1.20:8080/status?view=all", "browser": "safari"}),
    _active("web/active with a title of 256 characters", {**ACTIVE, "title": "T" * 256}),
    _active("web/active with a URL of 8192 characters", {**ACTIVE, "url": LONGEST_URL}),
    _active("web/active from an unlisted browser", {**ACTIVE, "browser": "other"}),
    _active("web/active with a Vietnamese title and an IDN host",
            {**ACTIVE, "url": "https://xn--bcher-kva.example/tin-tuc", "title": "Tin tức hôm nay",
             "browser": "samsung"}),
    ("web/inactive", "web-inactive", {"op": "inactive", "data": {"page_id": PAGE_ID}}),
    _capability("capability/hello Mac with Continue Browsing", "capability-hello", WEB_ON),
    _capability("capability/update iPhone with Continue Browsing", "capability-update",
                {"enabled": True, "send": False, "receive": True}),
]


def _variant(base_name: str, change) -> dict:
    instance = copy.deepcopy(next(inst for name, _, inst in POSITIVE if name == base_name))
    change(instance)
    return instance


def _set(path: list, value):
    def apply(instance):
        target = instance
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return apply


def _drop(path: list):
    def apply(instance):
        target = instance
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return apply


A = "web/active from Chrome on Android"
C = "capability/hello Mac with Continue Browsing"
NEGATIVE_SPECS = [
    ("web/active javascript: URL", "web-active", A, _set(["data", "url"], "javascript:alert(1)")),
    ("web/active file: URL", "web-active", A, _set(["data", "url"], "file:///etc/hosts")),
    ("web/active chrome: URL", "web-active", A, _set(["data", "url"], "chrome://settings")),
    ("web/active URL without a host", "web-active", A, _set(["data", "url"], "https:///path")),
    ("web/active URL with a leading space", "web-active", A, _set(["data", "url"], " https://example.com/")),
    ("web/active URL of 8193 characters", "web-active", A, _set(["data", "url"], LONGEST_URL + "b")),
    ("web/active title of 257 characters", "web-active", A, _set(["data", "title"], "T" * 257)),
    ("web/active empty title", "web-active", A, _set(["data", "title"], "")),
    ("web/active title null", "web-active", A, _set(["data", "title"], None)),
    ("web/active missing browser", "web-active", A, _drop(["data", "browser"])),
    ("web/active unknown browser id", "web-active", A, _set(["data", "browser"], "netscape")),
    ("web/active missing observed_at", "web-active", A, _drop(["data", "observed_at"])),
    ("web/active observed_at in seconds as a float", "web-active", A, _set(["data", "observed_at"], 1727150400.123)),
    ("web/active page_id not a v7 uuid", "web-active", A, _set(["data", "page_id"], PAIR_ID)),
    ("web/active unknown extra field", "web-active", A, _set(["data", "favicon"], "https://example.com/favicon.ico")),
    ("web/active with op inactive", "web-active", A, _set(["op"], "inactive")),
    ("web/inactive carrying a url", "web-inactive", "web/inactive", _set(["data", "url"], "https://example.com/")),
    ("web/inactive missing page_id", "web-inactive", "web/inactive", _drop(["data", "page_id"])),
    ("capability features.web missing receive", "capability-hello", C, _drop(["data", "features", "web", "receive"])),
    ("capability features.web send as a string", "capability-hello", C,
     _set(["data", "features", "web", "send"], "true")),
    ("capability features.web extra field", "capability-hello", C,
     _set(["data", "features", "web", "browsers"], ["chrome"])),
]

NEGATIVE = [(name, schema, _variant(base, change)) for name, schema, base, change in NEGATIVE_SPECS]
