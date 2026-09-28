"""Measure the planted effects in the `support` fixture from the written files.

Reads only `data/*.json` and the replayed Northwind customers/usage (the same
rows that are on shared), never the generator's internals, so a number here is
what an analyst, or Aito, could find in the data. Writes `data/lifts.json` and
prints the table the README quotes.

    python3 scripts/support_fixture/lifts.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate import DRIFT_DATE, INCOMING, northwind  # noqa: E402

DATA = HERE / "data"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def differs(a: dict, b: dict) -> bool:
    """Two rates differ at 95%: their Wilson intervals don't overlap (conservative)."""
    return a["ci95"][1] < b["ci95"][0] or b["ci95"][1] < a["ci95"][0]


def two_prop_z(k1: int, n1: int, k2: int, n2: int) -> float:
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return round((k1 / n1 - k2 / n2) / se, 2) if se else 0.0


def rate(rows, pred, outcome) -> dict:
    sel = [r for r in rows if pred(r)]
    k = sum(1 for r in sel if outcome(r))
    return {"n": len(sel), "p": round(k / len(sel), 3) if sel else None, "ci95": wilson(k, len(sel))}


def main(data: Path = DATA, incoming: Path | None = None) -> dict:
    # the full fixture: what is loaded plus the held-out incoming queue
    tickets = json.loads((data / "support_tickets.json").read_text())
    steps = json.loads((data / "support_steps.json").read_text())
    if incoming is not None and incoming.exists():
        held = json.loads(incoming.read_text())
        tickets, steps = tickets + held["tickets"], steps + held["steps"]
    customers, usage = northwind()
    cust = {c["customer_id"]: c for c in customers}
    for t in tickets:
        c = cust[t["customer"]]
        t["_size"], t["_plan"], t["_health"] = c["size"], c["plan"], c["health"]
    out: dict = {"tickets": len(tickets), "steps": len(steps)}

    # 1. category from words: how precise is the best single word?
    words = defaultdict(Counter)
    for t in tickets:
        for w in set(re.findall(r"[a-z]+", t["text"].lower())):
            words[w][t["category"]] += 1
    common = {w: c for w, c in words.items() if sum(c.values()) >= 50}
    prec = {w: max(c.values()) / sum(c.values()) for w, c in common.items()}
    out["category_words"] = {
        "words_seen_50x": len(common),
        "perfect_words": sum(p == 1.0 for p in prec.values()),
        "at_least_95": sum(p >= 0.95 for p in prec.values()),
        "examples": {w: round(prec[w], 3) for w in ("invoice", "sync", "password", "slow", "report", "access") if w in prec},
    }

    # 2. priority
    urgent = lambda t: any(u in t["text"] for u in ("urgent", "asap", "blocking our team", "production is down", "right now"))  # noqa: E731
    high = lambda t: t["priority"] == "high"  # noqa: E731
    out["priority_high"] = {
        "base": rate(tickets, lambda t: True, high),
        "urgent_words": rate(tickets, urgent, high),
        "no_urgent_words": rate(tickets, lambda t: not urgent(t), high),
        "plan_enterprise": rate(tickets, lambda t: t["_plan"] == "Enterprise", high),
        "plan_free": rate(tickets, lambda t: t["_plan"] == "Free", high),
        "category_bug": rate(tickets, lambda t: t["category"] == "bug", high),
        "category_how_to": rate(tickets, lambda t: t["category"] == "how_to", high),
    }
    ph = out["priority_high"]
    out["priority_high"]["plan_differs"] = differs(ph["plan_enterprise"], ph["plan_free"])
    out["priority_high"]["category_differs"] = differs(ph["category_bug"], ph["category_how_to"])

    # 3. drift: how login issues are resolved, before and after the SSO rollout.
    # Selected by the `issue` input, never by the resolution being measured.
    login = lambda t: t["issue"] == "login"  # noqa: E731
    sso = lambda t: t["resolution"] == "sso_reconnect"  # noqa: E731
    cut = DRIFT_DATE.strftime("%Y-%m")
    out["drift_sso"] = {
        "before": rate(tickets, lambda t: login(t) and t["month"] < cut, sso),
        "after": rate(tickets, lambda t: login(t) and t["month"] >= cut, sso),
        "all_access_before": rate(tickets, lambda t: t["category"] == "access" and t["month"] < cut, sso),
        "all_access_after": rate(tickets, lambda t: t["category"] == "access" and t["month"] >= cut, sso),
    }

    # 4. next step given the previous one (top transitions with support)
    trans = defaultdict(Counter)
    for s in steps:
        trans[(s["category"], s["previous_action"])][s["action"]] += 1
    base_next = Counter(s["action"] for s in steps)
    tops = []
    for (cat, prev), c in trans.items():
        n = sum(c.values())
        if n >= 100 and prev != "start":
            act, k = c.most_common(1)[0]
            tops.append({"category": cat, "previous": prev, "next": act, "n": n, "p": round(k / n, 3),
                         "lift": round((k / n) / (base_next[act] / len(steps)), 1)})
    out["next_step"] = sorted(tops, key=lambda x: -x["n"])[:8]

    # 5. detractor risk and the recovery lever
    det = lambda t: t["nps_after"] == "detractor"  # noqa: E731
    base = rate(tickets, lambda t: True, det)
    out["detractor"] = {
        "base": base,
        "repeat_30d": rate(tickets, lambda t: t["repeat_30d"] == "yes", det),
        "first_response_>24h": rate(tickets, lambda t: t["first_response"] == ">24h", det),
        "health_red": rate(tickets, lambda t: t["_health"] == "Red", det),
        "health_green": rate(tickets, lambda t: t["_health"] == "Green", det),
    }
    lever = {}
    for size in ("SMB", "Mid-market", "Enterprise"):
        acts = {r: rate(tickets, lambda t, r=r, size=size: t["_size"] == size and t["recovery"] == r, det)
                for r in ("none", "apology_credit", "priority_callback", "csm_outreach")}
        best = min(acts, key=lambda k: acts[k]["p"])
        lever[size] = {**acts, "best": best, "best_beats_none": differs(acts[best], acts["none"])}
    out["recovery_by_size"] = lever

    # 6. upsell acceptance
    offered = [t for t in tickets if t["upsell_offered"] == "yes"]
    acc = lambda t: t["upsell_accepted"] == "yes"  # noqa: E731
    out["upsell"] = {
        "base": rate(offered, lambda t: True, acc),
        "adoption_band_high": rate(offered, lambda t: t["adoption_band"] == "high", acc),
        "adoption_band_low": rate(offered, lambda t: t["adoption_band"] == "low", acc),
        "plan_free_or_starter": rate(offered, lambda t: t["_plan"] in ("Free", "Starter"), acc),
        "health_red": rate(offered, lambda t: t["_health"] == "Red", acc),
    }

    # 7. control: channel is deliberately NOT a cause of nps_after. Each channel is
    # tested against all the OTHER channels (a two-proportion z), not against a base
    # that includes itself.
    out["control_channel"] = {}
    for ch in ("email", "chat", "portal", "phone"):
        mine = [t for t in tickets if t["channel"] == ch]
        rest = [t for t in tickets if t["channel"] != ch]
        k1, k2 = sum(map(det, mine)), sum(map(det, rest))
        out["control_channel"][ch] = {**rate(mine, lambda t: True, det), "lift": round((k1 / len(mine)) / base["p"], 2),
                                      "z_vs_rest": two_prop_z(k1, len(mine), k2, len(rest))}
    out["control_holds"] = all(abs(v["z_vs_rest"]) < 1.96 for v in out["control_channel"].values())

    (data / "lifts.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(DATA, INCOMING), indent=1))
