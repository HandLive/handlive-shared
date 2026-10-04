"""Check clipboard-html.json: every case is run through the reference sanitizer again, so a hand edit of the JSON
(an input, an output or a rule) is caught. The Kotlin and Swift sanitizers are checked against the same file by their
own unit tests.
"""
import build_clipboard_html_vectors as ref

NAME = "clipboard-html.json"


def check_clipboard_html(c, doc) -> None:
    cases = doc["cases"]
    c.true(f"{NAME} has at least 20 cases", len(cases) >= 20)
    c.true(f"{NAME} case names are unique", len({x["name"] for x in cases}) == len(cases))
    for case in cases:
        c.eq(f"{NAME} {case['name']}: output", ref.sanitize(case["input"]), case["output"])
        c.eq(f"{NAME} {case['name']}: sanitizing twice changes nothing", ref.sanitize(case["output"]),
             case["output"])
    c.eq(f"{NAME} rules", doc["rules"], ref.build()[NAME]["rules"])
