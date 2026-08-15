"""Route-level parity: diff every /api/* response between two running backends.

`./do v2-parity` boots one backend on v1/master and one on v2/env.v2 and runs
this. The op-level probe (`./do v2-probe`) says which Aito query shapes differ;
this says which demo SURFACES differ — that is what gates the cutover.

    uv run python -m scripts.v2_parity http://127.0.0.1:4111 http://127.0.0.1:4112

Exit code is the number of routes that differ (0 = the demo behaves identically).
"""

from __future__ import annotations

import json
import sys

import httpx

# Routes with deterministic, Aito-backed output. The LLM-backed ones
# (/api/resolve-llm, /api/*-agent/chat) are excluded: live gpt-5-mini calls are
# non-deterministic, so a diff there says nothing about the API version.
ROUTES = [
    "/api/health",
    "/api/schema",
    "/api/resolve?text=my+broadband+keeps+dropping+every+evening",
    "/api/resolve?text=I+was+charged+twice+this+month",
    "/api/handoff",
    "/api/route?text=reset+my+router",
    "/api/opportunity",
    "/api/opportunity?industry=Manufacturing&service_line=Analytics",
    "/api/company-360",
    "/api/company-360?size=SMB",
    "/api/company-360?industry=Retail",
    "/api/sales-agent/tools",
    "/api/company-agent/tools",
]

# Keys whose value legitimately differs between the two deployments and says
# nothing about API-version parity.
VOLATILE = {"aito_url", "aito_ms", "ms", "latency_ms", "elapsed_ms", "engine", "cost_usd"}


def scrub(node):
    """Drop volatile keys so the diff shows behaviour, not wiring."""
    if isinstance(node, dict):
        return {k: scrub(v) for k, v in node.items() if k not in VOLATILE}
    if isinstance(node, list):
        return [scrub(v) for v in node]
    if isinstance(node, float):
        return round(node, 6)
    return node


def get(base: str, path: str):
    try:
        r = httpx.get(f"{base}{path}", timeout=120.0)
    except httpx.HTTPError as e:
        return None, {"unreachable": str(e)}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text[:300]}


def first_diff(a, b, path: str = "") -> str | None:
    """The first place two JSON trees disagree, as a readable path."""
    if type(a) is not type(b):
        return f"{path or '/'}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}/{k}: missing on v1"
            if k not in b:
                return f"{path}/{k}: missing on v2"
            d = first_diff(a[k], b[k], f"{path}/{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path or '/'}: {json.dumps(a)[:60]} vs {json.dumps(b)[:60]}"
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    v1, v2 = argv[0].rstrip("/"), argv[1].rstrip("/")
    print(f"v1: {v1}\nv2: {v2}\n")
    print(f"{'route':52} {'v1':>4} {'v2':>4}  verdict")
    print("-" * 100)

    diffs = []
    for path in ROUTES:
        s1, j1 = get(v1, path)
        s2, j2 = get(v2, path)
        if s1 != s2:
            verdict, detail = "STATUS", f"{s1} vs {s2}"
        else:
            detail = first_diff(scrub(j1), scrub(j2)) or ""
            verdict = "DIFF" if detail else "ok"
        print(f"{path[:52]:52} {str(s1):>4} {str(s2):>4}  {verdict}{(' — ' + detail[:34]) if detail else ''}")
        if verdict != "ok":
            diffs.append((path, verdict, detail))

    if diffs:
        print("\n" + "=" * 100)
        print(f"{len(diffs)} route(s) differ\n")
        for path, verdict, detail in diffs:
            print(f"### [{verdict}] {path}\n    {detail}\n")
    else:
        print("\nall routes identical — the demo behaves the same on v2")
    return len(diffs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
