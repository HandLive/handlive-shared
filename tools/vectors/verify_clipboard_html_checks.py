"""Check clipboard-html.json: every case is run through the reference sanitizer again, so a hand edit of the JSON
(an input, an output or a rule) is caught. The Kotlin and Swift sanitizers are checked against the same file by their
own unit tests. The sanitizer must also run in linear time: 1 MiB of `<a` or `<a"x"` that never completes a tag (no
`>` after it, or an unclosed quote before the last `>`) within PERF_BUDGET_S.
"""
import signal
import time

import build_clipboard_html_vectors as ref

NAME = "clipboard-html.json"
PERF_BUDGET_S = 1.0
PERF_REPEAT = 512 * 1024  # `<a` × this = 1 MiB
QUOTED_REPEAT = 1024 * 1024 // 5  # `<a"x"` × this ≈ 1 MiB
# (label, input, expected output): every `<a` failed to open a tag, so each one is escaped and stays text.
PERF_CASES = [
    ("1 MiB of `<a` without `>`", "<a" * PERF_REPEAT, "&lt;a" * PERF_REPEAT),
    ("1 MiB of `<a` then an unclosed quote before `>`", "<a" * PERF_REPEAT + "'>", "&lt;a" * PERF_REPEAT + "'>"),
    # Closed quotes between the tag starts, an unclosed one before the last `>`: a guard on the last `>` alone
    # stays quadratic here.
    ('1 MiB of `<a"x"` then an unclosed quote before `>`', '<a"x"' * QUOTED_REPEAT + "'>",
     '&lt;a"x"' * QUOTED_REPEAT + "'>"),
]


class _OverBudget(Exception):
    pass


def _timed_sanitize(html: str) -> tuple[str | None, float]:
    """The output and the seconds taken; None when the budget ran out (a quadratic sanitizer would take minutes)."""
    def stop(_signum, _frame):
        raise _OverBudget

    previous = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, PERF_BUDGET_S)
    start = time.perf_counter()
    try:
        return ref.sanitize(html), time.perf_counter() - start
    except _OverBudget:
        return None, time.perf_counter() - start
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def check_clipboard_html(c, doc) -> None:
    cases = doc["cases"]
    c.true(f"{NAME} has at least 20 cases", len(cases) >= 20)
    c.true(f"{NAME} case names are unique", len({x["name"] for x in cases}) == len(cases))
    for case in cases:
        c.eq(f"{NAME} {case['name']}: output", ref.sanitize(case["input"]), case["output"])
        c.eq(f"{NAME} {case['name']}: sanitizing twice changes nothing", ref.sanitize(case["output"]),
             case["output"])
    c.eq(f"{NAME} rules", doc["rules"], ref.build()[NAME]["rules"])
    for label, html, expected in PERF_CASES:
        out, seconds = _timed_sanitize(html)
        c.true(f"{NAME} {label}: sanitized within {PERF_BUDGET_S:.0f} s (took {seconds:.2f} s)", out is not None)
        c.true(f"{NAME} {label}: every `<a` escaped", out == expected)
