"""Nothing in the UI looks clickable without doing anything (CRO demo review
2026-09-28: "dead links" were a <div> styled as a link and a <button> with no
onClick, so every URL check passed).

Rules, over every .tsx file: a <button> has an onClick (or is a form submit), an
<a> or <Link> has an href, and no other element carries a link/button class.
Limits: a computed className={...} is not inspected, and a ">" inside a quoted
attribute value ends the tag early; neither occurs in this tree today.
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
LINKY_CLASS = re.compile(r"(?:^|-)(?:link|plink|btn|button)$")


def _open_tags(src: str):
    """(tag, attrs) for each JSX opening tag. Scans to the closing `>` at brace
    depth 0, so arrow functions in `onClick={() => ...}` don't end the tag."""
    for m in re.finditer(r"<([a-z][a-z0-9]*|Link)\b", src):
        depth, i = 0, m.end()
        while i < len(src):
            ch = src[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            i += 1
        yield m.group(1), src[m.end():i], src.count("\n", 0, m.start()) + 1


def dead_clickables(src: str) -> list[str]:
    dead = []
    for tag, attrs, line in _open_tags(src):
        if tag == "button" and "onClick" not in attrs and 'type="submit"' not in attrs:
            dead.append(f"{line}: <button> without onClick")
        elif tag in ("a", "Link") and "href" not in attrs:
            dead.append(f"{line}: <{tag}> without href")
        elif tag not in ("a", "Link", "button"):
            cls = re.search(r'className="([^"]*)"', attrs)
            if cls and any(LINKY_CLASS.search(c) for c in cls.group(1).split()):
                dead.append(f"{line}: <{tag} className=\"{cls.group(1)}\"> looks like a link but is not one")
    return dead


def test_the_check_catches_what_the_review_found():
    assert dead_clickables('<div className="rc-plink">API reference</div>')
    assert dead_clickables("<button>Start free trial →</button>")
    assert not dead_clickables('<button onClick={() => go(x > 1)}>Go</button>')
    assert not dead_clickables('<a className="rc-plink" href="/api/schema">Schema</a>')
    assert dead_clickables("<Link className=\"x\">Home</Link>")
    assert not dead_clickables('<Link href="/sales">Sales</Link>')


def test_nothing_in_the_frontend_is_a_dead_clickable():
    found = {str(p.relative_to(FRONTEND)): d
             for p in FRONTEND.rglob("*.tsx")
             if "node_modules" not in p.parts and ".next" not in p.parts
             and (d := dead_clickables(p.read_text()))}
    assert not found, found
