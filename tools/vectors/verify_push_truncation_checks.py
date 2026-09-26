"""Check the SMS text cut of push envelopes (CONN-04 step 5b, SMS-02 API 2 logic 3) independently of the generator.

Every sms/new push envelope is run through the rule again, from the texts before the cut (the truncation object, or
the plaintext itself for envelopes without one): body over 1,000 code points → its first 999 and "…"; while env_b64
is over 3,000 characters the body is replaced by a strictly shorter prefix followed by "…" (the longest that fits);
when even "…" does not fit, the snippet is cut the same way. env_b64 lengths come from arithmetic on the byte length of
the compact UTF-8 plaintext (nonce 24 + ciphertext + tag 16 in base64, inside the envelope JSON, in base64 again),
never from sealing, so a generator bug in the measurement shows up here.
"""
import json

ELLIPSIS = "…"
ENV_B64_MAX = 3000
STEP_SETS = [[], ["body_to_1000"], ["body_to_1000", "body_to_fit"], ["body_to_ellipsis", "snippet_to_fit"]]


def _b64_len(n: int) -> int:
    return (n + 2) // 3 * 4


def _compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def env_b64_length(v: dict, plaintext: str) -> int:
    payload = "A" * _b64_len(24 + len(plaintext.encode()) + 16)
    wire = _compact({"v": 1, "type": v["type"], "id": v["id"], "ts": v["ts"], "payload": payload})
    return _b64_len(len(wire.encode()))


def _shorter(text: str, fits) -> str | None:
    """The longest prefix-plus-"…" with fewer code points than text that fits, or None."""
    for keep in range(len(text) - 2, -1, -1):
        if fits(text[:keep] + ELLIPSIS):
            return text[:keep] + ELLIPSIS
    return None


def expected_cut(v: dict, before: dict) -> tuple[str, str, list[str]]:
    message, thread = before["data"]["message"], before["data"]["thread"]

    def length(body: str, snippet: str) -> int:
        obj = {"op": before["op"],
               "data": {"message": {**message, "body": body}, "thread": {**thread, "snippet": snippet}}}
        return env_b64_length(v, _compact(obj))

    body, snippet, steps = message["body"], thread["snippet"], []
    if len(body) > 1000:
        body, steps = body[:999] + ELLIPSIS, ["body_to_1000"]
    if length(body, snippet) <= ENV_B64_MAX:
        return body, snippet, steps
    shorter = _shorter(body, lambda b: length(b, snippet) <= ENV_B64_MAX)
    if shorter is not None:
        return shorter, snippet, steps + ["body_to_fit"]
    body = ELLIPSIS if len(body) > 1 else body
    shorter = _shorter(snippet, lambda s: length(body, s) <= ENV_B64_MAX)
    return body, shorter, steps + ["body_to_ellipsis", "snippet_to_fit"]


def check_cut(c, n: str, v: dict) -> list[str]:
    """Checks one sms/new push envelope; returns the steps its cut used."""
    plain = json.loads(v["plaintext"])
    c.eq(f"{n} plaintext is compact UTF-8 JSON", _compact(plain), v["plaintext"])
    c.eq(f"{n} env_b64 length by arithmetic", env_b64_length(v, v["plaintext"]), len(v["env_b64"]))
    t = v.get("truncation")
    before = json.loads(v["plaintext"])
    if t is not None:
        before["data"]["message"]["body"] = t["original_body"]
        before["data"]["thread"]["snippet"] = t["original_snippet"]
        c.eq(f"{n} original snippet = original body cut to 160 code points (SMS-01)", t["original_snippet"],
             t["original_body"][:160])
    body, snippet, steps = expected_cut(v, before)
    got = plain["data"]["message"]["body"], plain["data"]["thread"]["snippet"]
    c.eq(f"{n} body and snippet after the push cut", got, (body, snippet))
    if t is None:
        c.eq(f"{n} needs no cut", steps, [])
        return steps
    c.eq(f"{n} cut steps", t["steps"], steps)
    c.eq(f"{n} lengths", (t["body_code_points"], t["body_utf16_units"], t["snippet_code_points"], t["env_b64_length"]),
         (len(body), len(body.encode("utf-16-le")) // 2, len(snippet), len(v["env_b64"])))
    if steps[-1:] in (["body_to_fit"], ["snippet_to_fit"]):
        wider = json.loads(v["plaintext"])
        if steps[-1] == "body_to_fit":
            wider["data"]["message"]["body"] = t["original_body"][:len(body)] + ELLIPSIS
        else:
            wider["data"]["thread"]["snippet"] = t["original_snippet"][:len(snippet)] + ELLIPSIS
        more = env_b64_length(v, _compact(wider))
        c.eq(f"{n} one more code point kept", t["one_more_code_point_env_b64_length"], more)
        c.true(f"{n} one more code point would not fit", more > ENV_B64_MAX)
    else:
        c.true(f"{n} no longest-fit length without a fit step", "one_more_code_point_env_b64_length" not in t)
    return steps


def check_coverage(c, cut_vectors: list[tuple[dict, list[str]]]) -> None:
    """The cut vectors reach every branch of the rule, the 1,000 boundary, a non-ASCII text and an astral cut."""
    with_info = [(v, s) for v, s in cut_vectors if "truncation" in v]
    c.true("push-envelope: cut vectors cover every step sequence",
           all(any(s == want for _, s in with_info) for want in STEP_SETS))
    c.true("push-envelope: an ASCII body over 1,000 code points is cut at 1,000",
           any(s == ["body_to_1000"] and v["truncation"]["original_body"].isascii()
               and len(v["truncation"]["original_body"]) > 1000 for v, s in with_info))
    c.true("push-envelope: a body of exactly 1,000 code points is kept",
           any(len(v["truncation"]["original_body"]) == 1000 and not s for v, s in with_info))
    c.true("push-envelope: a non-ASCII body is cut to fit",
           any("body_to_fit" in s and not v["truncation"]["original_body"].isascii() for v, s in with_info))
    c.true("push-envelope: a cut after astral code points (UTF-16 units ≠ code points)",
           any(v["truncation"]["body_utf16_units"] != v["truncation"]["body_code_points"] and "body_to_1000" in s
               for v, s in with_info))
