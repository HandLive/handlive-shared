"""Reads the phone's screen with `uiautomator dump` and taps or types like a user, one visible step at a time.

UI texts come from the string catalog (shared/strings/ui-strings.json, English) by key, so a wording change in the
catalog does not break the harness. `step_delay` pauses after every action so a person can follow the run.
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from adb_device import Adb, AdbError

CATALOG = Path(__file__).resolve().parents[2] / "strings" / "ui-strings.json"
_STRINGS: dict[str, dict] | None = None


def en(key: str, **args) -> str:
    """The English text of a catalog key, with {args} filled in (plural strings use the `other` form)."""
    global _STRINGS
    if _STRINGS is None:
        _STRINGS = {s["key"]: s for s in json.loads(CATALOG.read_text(encoding="utf-8"))["strings"]}
    text = _STRINGS[key]["en"]
    if isinstance(text, dict):
        text = text["one"] if args.get("count") == 1 and "one" in text else text["other"]
    for name, value in args.items():
        text = text.replace("{" + name + "}", str(value))
    return text


@dataclass
class Node:
    text: str
    rid: str
    desc: str
    cls: str
    package: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2


def parse_dump(xml: str) -> list[Node]:
    root = ET.fromstring(xml[xml.index("<"):xml.rindex(">") + 1])
    nodes = []
    for el in root.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", el.get("bounds", ""))
        if not m:
            continue
        nodes.append(Node(el.get("text", ""), el.get("resource-id", ""), el.get("content-desc", ""),
                          el.get("class", ""), el.get("package", ""), el.get("clickable") == "true",
                          tuple(int(g) for g in m.groups())))
    return nodes


class Ui:
    def __init__(self, adb: Adb, step_delay: float = 1.0) -> None:
        self.adb = adb
        self.step_delay = step_delay

    def pause(self) -> None:
        if self.step_delay > 0:
            time.sleep(self.step_delay)

    def dump(self) -> list[Node]:
        """One dump; retried because uiautomator refuses while the screen animates ("could not get idle state")."""
        last = ""
        for _ in range(4):
            out = self.adb.shell("uiautomator dump /sdcard/hl_e2e_ui.xml", timeout=40, check=False)
            if "dumped to" in out:
                xml = self.adb.run("exec-out", "cat", "/sdcard/hl_e2e_ui.xml", timeout=20)
                if "<hierarchy" in xml:
                    return parse_dump(xml)
            last = out.strip()
            time.sleep(1)
        raise AdbError(f"uiautomator dump failed: {last[:200]}")

    @staticmethod
    def find(nodes: list[Node], text: str | None = None, contains: str | None = None, rid: str | None = None,
             desc: str | None = None) -> list[Node]:
        out = []
        for n in nodes:
            if text is not None and n.text != text and n.desc != text:
                continue
            if contains is not None and contains not in n.text and contains not in n.desc:
                continue
            if rid is not None and n.rid != rid:
                continue
            if desc is not None and n.desc != desc:
                continue
            out.append(n)
        return out

    def wait_any(self, timeout: float, **queries: dict) -> tuple[str, Node] | None:
        """Waits until one of the named queries (keyword → find() arguments) matches; returns (name, node)."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                nodes = self.dump()
            except AdbError:
                nodes = []
            for name, query in queries.items():
                found = self.find(nodes, **query)
                if found:
                    return name, found[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.7)

    def wait(self, timeout: float = 20, **query) -> Node | None:
        hit = self.wait_any(timeout, only=query)
        return hit[1] if hit else None

    def tap(self, node: Node) -> None:
        x, y = node.center
        self.adb.shell(f"input tap {x} {y}")
        self.pause()

    def tap_text(self, text: str, timeout: float = 20) -> bool:
        node = self.wait(timeout, text=text)
        if node is None:
            return False
        self.tap(node)
        return True

    def type_digits(self, digits: str) -> None:
        """Typed one key at a time, visibly, like a person entering a PIN."""
        for d in digits:
            self.adb.shell(f"input keyevent KEYCODE_{d}")
            time.sleep(min(self.step_delay, 0.4))
        self.pause()

    def screen_texts(self) -> list[str]:
        return [n.text for n in self.dump() if n.text]

    def open_notifications(self) -> None:
        self.adb.shell("cmd statusbar expand-notifications", check=False)
        self.pause()

    def close_notifications(self) -> None:
        self.adb.shell("cmd statusbar collapse", check=False)

    def home(self) -> None:
        self.adb.shell("input keyevent KEYCODE_HOME", check=False)
        self.pause()
