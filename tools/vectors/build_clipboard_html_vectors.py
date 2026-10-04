"""Build clipboard-html.json: the HTML sanitizer every platform runs on a text clip's `html` (04-clipboard CLIP-01
API 5 `html`, plan 20261005-clipboard-html §6). The reference implementation below defines the rules; Kotlin
(core/protocol) and Swift (HLProtocol) must reproduce every case byte for byte.

Rules: comments go; tag and attribute names are case-insensitive, output tags are lowercase; DROP_CONTENT tags go
with everything up to their matching close tag (or the end when unclosed); KEEP tags stay with their allowed
attributes only, re-serialized ` name="value"` in a fixed order with `"` `<` `>` escaped; every other tag is
unwrapped (tag gone, content kept); `href` keeps http/https/mailto only, `img src` keeps http/https only and an
`img` without a kept `src` is dropped whole; `width height colspan rowspan` keep digits only; void tags `br hr img`
never close; text between tags is copied as is.
"""
import re

SPEC = "docs/detailed-design/04-clipboard.md CLIP-01 API 5 (html), plans/20261005-clipboard-html/plan.md §6"

DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript", "head",
                "title", "textarea", "select", "button", "form", "input", "video", "audio", "canvas", "link", "meta",
                "base", "applet", "frame", "frameset"}
KEEP = {"a", "abbr", "b", "blockquote", "br", "caption", "code", "div", "em", "figcaption", "figure", "h1", "h2", "h3",
        "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "s", "span", "strong", "sub", "sup", "table",
        "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul"}
VOID = {"br", "hr", "img"}
ALLOWED_ATTRS = {"a": ["href"], "img": ["src", "alt", "width", "height"], "td": ["colspan", "rowspan"],
                 "th": ["colspan", "rowspan"]}
URL_SCHEMES = {"href": ("http:", "https:", "mailto:"), "src": ("http:", "https:")}
DIGITS = {"width", "height", "colspan", "rowspan"}

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
ATTR_RE = re.compile(r"([A-Za-z_:][-A-Za-z0-9_:.]*)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))?")


def _attribute_value(raw: str | None) -> str:
    if raw is None:
        return ""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def _escape(value: str) -> str:
    return value.replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _render_open(name: str, attrs_text: str) -> str | None:
    found = {}
    for m in ATTR_RE.finditer(attrs_text):
        key = m.group(1).lower()
        if key in found or key not in ALLOWED_ATTRS.get(name, []):
            continue
        value = _attribute_value(m.group(2))
        if key in URL_SCHEMES:
            value = value.strip()
            if not value.lower().startswith(URL_SCHEMES[key]):
                continue
        elif key in DIGITS and not (value and value.isdigit()):
            continue
        found[key] = value
    if name == "img" and "src" not in found:
        return None
    out = "<" + name
    for key in ALLOWED_ATTRS.get(name, []):
        if key in found:
            out += f' {key}="{_escape(found[key])}"'
    return out + ">"


def sanitize(html: str) -> str:
    text = COMMENT_RE.sub("", html)
    out = []
    pos = 0
    while True:
        m = TAG_RE.search(text, pos)
        if m is None:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        closing, name, attrs_text = m.group(1) == "/", m.group(2).lower(), m.group(3)
        pos = m.end()
        if name in DROP_CONTENT:
            if not closing:
                close = re.compile(rf"</{name}\s*>", re.I).search(text, pos)
                pos = close.end() if close else len(text)
            continue
        if name not in KEEP:
            continue  # unwrap: the tag goes, its content stays
        if closing:
            if name not in VOID:
                out.append(f"</{name}>")
            continue
        rendered = _render_open(name, attrs_text)
        if rendered is not None:
            out.append(rendered)
    return "".join(out)


# (name, input): the expected output comes from the reference implementation above.
CASES = [
    ("plain paragraph kept", "<p>Hello <b>world</b></p>"),
    ("style, class and data attributes dropped", '<p style="color:red" class="x" data-y="1">Hi</p>'),
    ("script dropped with its content", "<script>alert(1)</script><p>ok</p>"),
    ("javascript href dropped, the link stays", '<a href="javascript:alert(1)">x</a>'),
    ("https href kept, target and onclick dropped",
     '<a href="https://e.com/a?b=1&amp;c=2" target="_blank" onclick="x()">link</a>'),
    ("img keeps src alt width height, drops loading",
     '<img src="https://e.com/i.png" alt="pic" width="640" height="480" loading="lazy">'),
    ("img with a data URL is dropped whole", '<p><img src="data:image/png;base64,AAAA">x</p>'),
    ("tag name lowercased, attribute value kept as written", '<IMG SRC="HTTP://E.COM/X.JPG">'),
    ("iframe dropped inside a div", '<div><iframe src="https://x"></iframe>text</div>'),
    ("style element dropped, br kept", "<style>p{}</style><p>a<br>b</p>"),
    ("comment removed", "<!-- c --><p>a</p>"),
    ("section and font unwrapped", '<section><h2>T</h2><font color="red">x</font></section>'),
    ("table cell keeps colspan, drops style", '<table><tr><td colspan="2" style="x">a</td></tr></table>'),
    ("entities in text untouched", "<p>5 &lt; 6 &amp; 7</p>"),
    ("svg dropped with its content", '<svg onload="x"><circle/></svg><p>k</p>'),
    ("event attribute dropped", '<p onmouseover="x">t</p>'),
    ("href trimmed", '<a href=" https://e.com ">t</a>'),
    ("self-closing void tags normalized", "<br/><hr />"),
    ("unclosed script drops to the end", "<p>a</p><script>x"),
    ("non-digit rowspan dropped", '<td rowspan="abc">x</td>'),
    ("meta dropped", '<meta charset="utf-8"><p>m</p>'),
    ("nbsp entity untouched", "<p>&nbsp;</p>"),
    ("single-quoted value re-escaped", "<a href='https://e.com/?q=\"x\"'>t</a>"),
    ("uppercase tags lowercased", "<P>Upper</P>"),
    ("relative img src dropped whole", '<p>x<img src="/a.png">y</p>'),
    ("mailto href kept", '<a href="MAILTO:me@example.com">mail</a>'),
    ("stray closing br dropped, unknown closing tag dropped", "<p>a</br>b</font></p>"),
    ("a less-than that is not a tag stays text", "<p>a < b and c <3 d</p>"),
    ("nested keep inside drop content goes with it", "<noscript><p>never</p></noscript><p>shown</p>"),
    ("attribute order fixed: alt before src in input", '<img alt="a" height="2" src="https://e.com/p.png" width="1">'),
]


def build() -> dict:
    cases = [{"name": name, "input": html, "output": sanitize(html)} for name, html in CASES]
    return {"clipboard-html.json": {
        "spec": SPEC,
        "description": "HtmlClipSanitizer: input → output; a platform's sanitizer must produce `output` byte for byte",
        "rules": {"drop_with_content": sorted(DROP_CONTENT), "keep": sorted(KEEP), "void": sorted(VOID),
                  "allowed_attributes": ALLOWED_ATTRS, "url_schemes": {k: list(v) for k, v in URL_SCHEMES.items()},
                  "digits_only": sorted(DIGITS)},
        "cases": cases}}
