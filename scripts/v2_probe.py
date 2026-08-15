"""Op-level parity probe: every Aito query shape this demo uses, run against
`/api/v1` and `/api/v2` on the same data, diffed.

This is the instrument behind `docs/v2-migration.md`. Re-run it as core lands
fixes; when it reports no breaks, the demo can cut over.

    ./do v2-probe                 # master (v1) vs env.v2 (v2)
    ./do v2-probe --env ""        # both surfaces against master, isolating the
                                  # API version from the environment

Exit code is the number of breaks (0 = full parity), so CI can gate on it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from src.config import load_config

# (label, method, path suffix, body) — mirrors src/aito_client.py's surface plus
# the shapes src/app.py actually sends.
OPS: list[tuple[str, str, str, dict | None]] = [
    ("schema", "GET", "schema", None),
    ("predict/bare text", "POST", "_predict",
     {"from": "resolutions", "where": {"text": "my broadband keeps dropping every evening"},
      "predict": "intent", "limit": 3}),
    ("predict/$has token", "POST", "_predict",
     {"from": "resolutions", "where": {"text": {"$has": "broadband"}}, "predict": "intent", "limit": 3}),
    ("predict/select+$why", "POST", "_predict",
     {"from": "resolutions", "where": {"text": {"$has": "broadband"}}, "predict": "intent",
      "limit": 1, "select": ["$p", "$value", "$why"]}),
    ("predict/nullable target", "POST", "_predict",
     {"from": "tool_calls", "where": {"text": "reset my router"}, "predict": "tool", "limit": 5}),
    ("estimate", "POST", "_estimate",
     {"from": "engagements", "where": {"service_line": "Data Platform"}, "estimate": "effort_days"}),
    ("recommend", "POST", "_recommend",
     {"from": "outreach", "where": {"target_industry": "Manufacturing"},
      "recommend": "channel", "goal": {"meeting": "yes"}, "limit": 4}),
    ("relate", "POST", "_relate",
     {"from": "customers", "where": {"churned": "yes"}, "relate": ["plan", "size"]}),
    ("relate/$on", "POST", "_relate",
     {"from": "customers", "relate": {"$on": [{"churned": "yes"}, {"size": "SMB"}]}}),
    ("query", "POST", "_query", {"from": "engagements", "limit": 3}),
    ("query/count", "POST", "_query", {"from": "resolutions", "limit": 0}),
    ("query/nullable col", "POST", "_query",
     {"from": "resolutions", "where": {"location": "Helsinki"}, "limit": 2}),
    ("query/implicit AND", "POST", "_query",
     {"from": "resolutions", "where": {"intent": "refund", "customer": "cust_0001"}, "limit": 0}),
    ("query/$and", "POST", "_query",
     {"from": "resolutions", "where": {"$and": [{"intent": "refund"}, {"customer": "cust_0001"}]}, "limit": 0}),
    ("query/$or", "POST", "_query",
     {"from": "resolutions", "where": {"$or": [{"intent": "refund"}, {"intent": "repair_help"}]}, "limit": 0}),
    ("match", "POST", "_match",
     {"from": "resolutions", "where": {"text": {"$has": "broadband"}}, "match": "intent", "limit": 3}),
    ("search", "POST", "_search", {"from": "resolutions", "where": {"text": "router"}, "limit": 3}),
    ("search/$has", "POST", "_search",
     {"from": "resolutions", "where": {"text": {"$has": "broadband"}}, "limit": 3}),
    ("search/orderBy $similarity", "POST", "_search",
     {"from": "resolutions", "where": {"text": "router"}, "orderBy": "$similarity", "limit": 3}),
    ("similarity", "POST", "_similarity",
     {"from": "resolutions", "where": {"text": {"$has": "broadband"}},
      "similarity": {"text": "broadband"}, "limit": 3}),
]

# v2 renamed the predicted value; compare on either spelling so a pure rename
# does not drown out the real behavioural differences.
_VALUE = ("feature", "$value")


def _val(hit: dict):
    for k in _VALUE:
        if k in hit:
            return hit[k]
    return None


def fingerprint(payload) -> object:
    """A small, comparable summary — the parts a demo actually renders."""
    if not isinstance(payload, dict):
        return payload
    if "hits" in payload:
        out = []
        for h in (payload["hits"] or [])[:3]:
            if not isinstance(h, dict):
                out.append(h)
                continue
            row: dict = {}
            v = _val(h)
            if v is not None:
                row["value"] = v
            for k in ("$p", "lift", "$score"):
                if isinstance(h.get(k), float):
                    row[k] = round(h[k], 6)
            if "related" in h:
                row["related"] = h["related"]
            out.append(row)
        return {"total": payload.get("total"), "top": out}
    if "estimate" in payload:
        e = payload["estimate"]
        return {"estimate": round(e, 6) if isinstance(e, float) else e}
    if "schema" in payload:
        return {"tables": sorted(payload["schema"].keys())}
    return payload


def call(base: str, ver: str, key: str, method: str, suffix: str, body):
    url = f"{base}/api/{ver}/{suffix}"
    try:
        r = httpx.request(method, url,
                          headers={"x-api-key": key, "content-type": "application/json"},
                          json=body, timeout=30.0)
    except httpx.HTTPError as e:
        return None, {"unreachable": str(e)}, url
    try:
        return r.status_code, r.json(), url
    except ValueError:
        return r.status_code, {"raw": r.text[:200]}, url


def err_of(payload) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
        if payload.get("message"):
            return str(payload["message"])
    return json.dumps(payload)[:160]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="v2",
                    help="Aito environment for the v2 side ('' = master). Default: v2")
    args = ap.parse_args()

    cfg = load_config()
    # Strip any env already folded in by config so both sides are explicit here.
    root = cfg.aito_url
    if cfg.aito_env:
        root = root[: -len(f"/env/{cfg.aito_env}")]
    v1_base = root
    v2_base = f"{root}/env/{args.env}" if args.env else root

    print(f"v1: {v1_base}/api/v1")
    print(f"v2: {v2_base}/api/v2\n")
    print(f"{'op':30} {'v1':>4} {'v2':>4}  verdict")
    print("-" * 92)

    breaks = []
    for label, method, suffix, body in OPS:
        s1, j1, _ = call(v1_base, "v1", cfg.aito_key, method, suffix, body)
        s2, j2, u2 = call(v2_base, "v2", cfg.aito_key, method, suffix, body)
        ok1 = s1 is not None and s1 < 400
        ok2 = s2 is not None and s2 < 400

        if ok1 and not ok2:
            kind, detail = "BREAK", err_of(j2)
        elif ok2 and not ok1:
            kind, detail = "v2-only ok", ""
        elif not ok1 and not ok2:
            kind, detail = "both fail", err_of(j2)
        else:
            f1, f2 = fingerprint(j1), fingerprint(j2)
            if f1 == f2:
                kind, detail = "ok", ""
            else:
                kind = "DIFF"
                detail = f"v1={json.dumps(f1)[:150]}  v2={json.dumps(f2)[:150]}"

        print(f"{label:30} {str(s1):>4} {str(s2):>4}  {kind}{(' — ' + detail[:44]) if detail else ''}")
        if kind in ("BREAK", "DIFF", "both fail"):
            breaks.append((kind, label, s1, s2, u2, body, detail))

    if breaks:
        print("\n" + "=" * 92)
        print(f"{len(breaks)} difference(s) — see docs/v2-migration.md\n")
        for kind, label, s1, s2, url, body, detail in breaks:
            print(f"### [{kind}] {label}   v1={s1} v2={s2}")
            print(f"    {url}")
            if body is not None:
                print(f"    {json.dumps(body)}")
            print(f"    {detail}\n")
    else:
        print("\nfull parity — the demo can cut over to v2")
    return len(breaks)


if __name__ == "__main__":
    sys.exit(main())
