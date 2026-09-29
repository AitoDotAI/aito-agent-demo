"""Measure the planted effects in the `support` fixture from the written files.

Reads only `data/*.json`, the held-out queue and the replayed Northwind
customers (the same rows that are on shared), never the generator's internals,
so a number here is what an analyst, or Aito, could find in the data. Writes
`data/lifts.json`.

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
    tickets = json.loads((data / "support_tickets.json").read_text())
    steps = json.loads((data / "support_steps.json").read_text())
    contacts = {c["contact_id"]: c for c in json.loads((data / "support_contacts.json").read_text())}
    if incoming is not None and incoming.exists():
        held = json.loads(incoming.read_text())
        tickets, steps = tickets + held["tickets"], steps + held["steps"]
    customers, _ = northwind()
    cust = {c["customer_id"]: c for c in customers}
    for t in tickets:
        c = cust[t["customer"]]
        t["_size"], t["_plan"], t["_health"] = c["size"], c["plan"], c["health"]
        t["_role"] = contacts[t["contact"]]["role"] if t["contact"] else None
    out: dict = {"tickets": len(tickets), "steps": len(steps), "contacts": len(contacts),
                 "accounts": len({t["customer"] for t in tickets})}

    # 1. who: a known contact is a lookup; a new address still names its account's domain
    by_domain = defaultdict(set)
    for t in tickets:
        by_domain[t["sender_domain"]].add(t["customer"])
    out["who"] = {"known_contact_share": round(sum(t["contact"] is not None for t in tickets) / len(tickets), 3),
                  "domains": len(by_domain),
                  "domains_naming_one_account": sum(len(v) == 1 for v in by_domain.values())}

    # 2. category from words; from the contact's role; the account's recurring issue
    words = defaultdict(Counter)
    for t in tickets:
        for w in set(re.findall(r"[a-z]+", t["text"].lower())):
            words[w][t["category"]] += 1
    common = {w: c for w, c in words.items() if sum(c.values()) >= 100}
    prec = {w: max(c.values()) / sum(c.values()) for w, c in common.items()}
    out["category_words"] = {"words_seen_100x": len(common), "perfect_words": sum(p == 1.0 for p in prec.values()),
                             "examples": {w: round(prec[w], 3) for w in ("invoice", "sync", "password", "report")
                                          if w in prec}}
    billing = lambda t: t["category"] == "billing"  # noqa: E731
    integ = lambda t: t["category"] == "integration"  # noqa: E731
    out["role_to_category"] = {
        "billing_from_finance": rate(tickets, lambda t: t["_role"] == "finance", billing),
        "billing_from_others": rate(tickets, lambda t: t["_role"] not in (None, "finance"), billing),
        "integration_from_developer": rate(tickets, lambda t: t["_role"] == "developer", integ),
        "integration_from_others": rate(tickets, lambda t: t["_role"] not in (None, "developer"), integ),
    }
    per_acc = defaultdict(Counter)
    for t in tickets:
        per_acc[t["customer"]][t["issue"]] += 1
    top_share = [c.most_common(1)[0][1] / sum(c.values()) for c in per_acc.values()]
    base_issue = Counter(t["issue"] for t in tickets)
    out["recurring_issue"] = {"mean_top_issue_share_per_account": round(sum(top_share) / len(top_share), 3),
                              "largest_issue_share_overall": round(max(base_issue.values()) / len(tickets), 3)}

    # 3. product: named in the text
    names = {"PRD-" + n.lower(): n for n in ("dashboards", "reports", "api", "automations", "integrations",
                                            "mobile", "forecasting", "governance")}
    out["product"] = {"named_in_text": round(sum(names.get(t["product"], "#").lower() in t["text"].lower()
                                                 for t in tickets) / len(tickets), 3)}

    # 4. priority: the desk's triage rules
    urgent = lambda t: any(u in t["text"] for u in ("urgent", "asap", "blocking our team", "production is down", "right now"))  # noqa: E731
    ent_bug = lambda t: t["category"] == "bug" and t["_plan"] == "Enterprise"  # noqa: E731
    out["priority"] = {
        "high_with_urgent_words": rate(tickets, urgent, lambda t: t["priority"] == "high"),
        "high_enterprise_bug": rate(tickets, lambda t: not urgent(t) and ent_bug(t), lambda t: t["priority"] == "high"),
        "high_otherwise": rate(tickets, lambda t: not urgent(t) and not ent_bug(t), lambda t: t["priority"] == "high"),
        "low_how_to": rate(tickets, lambda t: not urgent(t) and t["category"] == "how_to", lambda t: t["priority"] == "low"),
    }

    # 5. drift: how login issues are resolved, before and after the SSO rollout
    login = lambda t: t["issue"] == "login"  # noqa: E731
    sso = lambda t: t["resolution"] == "sso_reconnect"  # noqa: E731
    cut = DRIFT_DATE.strftime("%Y-%m")
    out["drift_sso"] = {
        "before": rate(tickets, lambda t: login(t) and t["month"] < cut, sso),
        "after": rate(tickets, lambda t: login(t) and t["month"] >= cut, sso),
        "all_access_before": rate(tickets, lambda t: t["category"] == "access" and t["month"] < cut, sso),
        "all_access_after": rate(tickets, lambda t: t["category"] == "access" and t["month"] >= cut, sso),
    }

    # 6. next step given the previous one
    trans = defaultdict(Counter)
    for s in steps:
        trans[(s["category"], s["previous_action"])][s["action"]] += 1
    base_next = Counter(s["action"] for s in steps)
    tops = []
    for (cat, prev), c in trans.items():
        n = sum(c.values())
        if n >= 300 and prev != "start":
            act, k = c.most_common(1)[0]
            tops.append({"category": cat, "previous": prev, "next": act, "n": n, "p": round(k / n, 3),
                         "lift": round((k / n) / (base_next[act] / len(steps)), 1)})
    out["next_step"] = sorted(tops, key=lambda x: -x["n"])[:8]

    # 7. detractor risk and the recovery lever
    det = lambda t: t["nps_after"] == "detractor"  # noqa: E731
    base = rate(tickets, lambda t: True, det)
    out["detractor"] = {
        "base": base,
        "repeat_same_issue_30d": rate(tickets, lambda t: t["repeat_30d"] == "yes", det),
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

    # 8. upsell acceptance
    offered = [t for t in tickets if t["upsell_offered"] == "yes"]
    acc = lambda t: t["upsell_accepted"] == "yes"  # noqa: E731
    out["upsell"] = {
        "base": rate(offered, lambda t: True, acc),
        "adoption_band_high": rate(offered, lambda t: t["adoption_band"] == "high", acc),
        "adoption_band_low": rate(offered, lambda t: t["adoption_band"] == "low", acc),
        "health_red": rate(offered, lambda t: t["_health"] == "Red", acc),
    }

    # 9. control: channel is deliberately NOT a cause of nps_after; each channel is
    # tested against all the OTHER channels (a two-proportion z)
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
