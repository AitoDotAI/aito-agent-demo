"""Aito only vs Aito + LLM vs LLM only, on the 300 held-out support tickets.

For each ticket and each decision (product, category, priority, resolution,
first step), against what really happened:
- Aito only: the envelope's predictions (src/support_envelope.py);
- LLM only: one gpt-5-mini call makes every decision from the full label lists,
  given the ticket text and the intake context (the contact's role, the account's
  plan and size), but not the desk's history;
- Aito + LLM: Aito's answer where its $p >= 0.85; the rest go to ONE gpt-5-mini
  call, with Aito's top 3 (and their $p) offered first. No call if Aito was sure
  of everything.
It records accuracy (95% Wilson), LLM calls, tokens, cost and latency per mode.
LLM latency is the successful call's own time, excluding rate-limit backoff.

Resumable: each ticket is appended to results/compare_modes.jsonl, and a rerun
skips the tickets already there. On a synthetic fixture with planted effects.

    AITO_API_VERSION=v2 uv run python scripts/support_fixture/compare_modes.py [--summary]
"""

from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import generate  # noqa: E402
import seed_company as nw  # noqa: E402
from src import app as A  # noqa: E402
from src.support_envelope import AUTO, DETOURS, envelope, load_incoming  # noqa: E402
from src.support_llm import decide  # noqa: E402

RESULTS = HERE / "results"
LOG = RESULTS / "compare_modes.jsonl"
SUMMARY = RESULTS / "compare_modes.json"
TARGETS = ["product", "category", "priority", "resolution", "first_step"]
OPTIONS = {
    "product": [p["product_id"] for p in nw.PRODUCTS],
    "category": list(generate.TOPICS),
    "priority": ["high", "normal", "low"],
    "resolution": sorted({res for c in generate.TOPICS.values() for res, _ in c.values()} | {"sso_reconnect"}),
    "first_step": sorted({path[0] for path in generate.PATHS.values()}),
}


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def truth_of(t: dict, steps: list[dict]) -> dict:
    real = [s["action"] for s in steps if s["action"] not in DETOURS]
    return {"product": t["product"], "category": t["category"], "priority": t["priority"],
            "resolution": t["resolution"], "first_step": real[0] if real else None}


def run() -> None:
    aito = A._support_client()
    q = load_incoming()
    customers = {c["customer_id"]: c for c in nw.build_customers(random.Random(nw.SEED))}
    contacts = {c["contact_id"]: c for c in json.loads((HERE / "data" / "support_contacts.json").read_text())}
    done = {json.loads(line)["ticket_id"] for line in LOG.read_text().splitlines()} if LOG.exists() else set()
    RESULTS.mkdir(exist_ok=True)
    for i, tid in enumerate(q["order"]):
        if tid in done:
            continue
        t, steps = q["tickets"][tid], q["steps"].get(tid, [])
        env = envelope(aito, t, steps)
        by = {s["key"]: s for s in env["steps"]}
        aito_vals = {k: by[k]["value"] for k in TARGETS}
        aito_p = {k: by[k]["p"] for k in TARGETS}
        acct = customers.get(t["customer"], {})
        role = contacts[t["contact"]]["role"] if t.get("contact") in contacts else "unknown (new address)"
        context = {"contact role": role, "account plan": acct.get("plan"), "account size": acct.get("size")}

        llm = decide(t, context, OPTIONS)
        unsure = [k for k in TARGETS if aito_p[k] is None or aito_p[k] < AUTO]
        coop_vals, coop = dict(aito_vals), None
        if unsure:
            short = {k: [(by[k]["value"], by[k]["p"])] + [(a["value"], a["p"]) for a in by[k]["alternatives"]]
                     for k in unsure}
            coop = decide(t, context, {k: OPTIONS[k] for k in unsure}, short)
            coop_vals.update({k: v for k, v in coop.values.items() if v is not None})
        row = {"ticket_id": tid, "truth": truth_of(t, steps), "aito": aito_vals, "aito_p": aito_p,
               "aito_wall_ms": env["wall_ms"],
               "llm_only": {"values": llm.values, "in": llm.input_tokens, "out": llm.output_tokens, "ms": round(llm.latency_ms)},
               "coop": {"values": coop_vals, "unsure": unsure,
                        "in": coop.input_tokens if coop else 0, "out": coop.output_tokens if coop else 0,
                        "ms": round(coop.latency_ms) if coop else 0}}
        with LOG.open("a") as f:
            f.write(json.dumps(row) + "\n")
        if (i + 1) % 25 == 0:
            print(f"{i + 1}/{len(q['order'])}", flush=True)


def selective(rows: list[dict]) -> dict:
    """Hand a step to the LLM only where, among tickets Aito was unsure of, the LLM
    was right more often. The policy is chosen on the OLDER half of the queue and
    scored on the NEWER half, so it is not judged on the tickets that chose it."""
    order = {t["ticket_id"]: t["created_at"] for t in json.loads(generate.INCOMING.read_text())["tickets"]}
    rows = sorted(rows, key=lambda r: order[r["ticket_id"]])
    fit, test = rows[: len(rows) // 2], rows[len(rows) // 2:]
    policy, evidence = {}, {}
    for k in TARGETS:
        u = [r for r in fit if k in r["coop"]["unsure"] and r["truth"][k] is not None]
        a = sum(r["aito"][k] == r["truth"][k] for r in u)
        m = sum(r["coop"]["values"][k] == r["truth"][k] for r in u)
        policy[k] = "llm" if m > a else "aito"
        evidence[k] = {"unsure_n": len(u), "aito_right": a, "llm_right": m}

    def pick(r, k, pol):
        return r["coop"]["values"][k] if k in r["coop"]["unsure"] and pol[k] == "llm" else r["aito"][k]

    scored = {}
    for name, pol in (("aito_only", {k: "aito" for k in TARGETS}), ("every_unsure_step", {k: "llm" for k in TARGETS}),
                      ("selective", policy)):
        allk = sum(all(pick(r, k, pol) == r["truth"][k] for k in TARGETS if r["truth"][k]) for r in test)
        calls = sum(any(k in r["coop"]["unsure"] and pol[k] == "llm" for k in TARGETS) for r in test)
        scored[name] = {"all_five_right": round(allk / len(test), 3), "ci95": wilson(allk, len(test)),
                        "tickets_calling_llm": round(calls / len(test), 3),
                        "per_step": {k: round(sum(pick(r, k, pol) == r["truth"][k] for r in test if r["truth"][k])
                                               / sum(1 for r in test if r["truth"][k]), 3) for k in TARGETS}}
    return {"policy": policy, "fit_evidence": evidence, "fit_n": len(fit), "test_n": len(test), "scored_on_test": scored}


def summarize() -> dict:
    from src.llm_agent import cost_usd
    rows = [json.loads(line) for line in LOG.read_text().splitlines()]
    n = len(rows)
    out = {"caveat": "on a synthetic fixture with planted effects; 300 held-out tickets; gpt-5-mini",
           "tickets": n, "accuracy": {}, "llm": {}, "latency_ms": {}}
    for mode, get in (("aito_only", lambda r: r["aito"]), ("aito_plus_llm", lambda r: r["coop"]["values"]),
                      ("llm_only", lambda r: r["llm_only"]["values"])):
        acc = {}
        for k in TARGETS:
            pairs = [(get(r)[k], r["truth"][k]) for r in rows if r["truth"][k] is not None]
            right = sum(a == b for a, b in pairs)
            acc[k] = {"share": round(right / len(pairs), 3), "ci95": wilson(right, len(pairs)), "n": len(pairs)}
        all_right = sum(all(get(r)[k] == r["truth"][k] for k in TARGETS if r["truth"][k] is not None) for r in rows)
        acc["all_five_right"] = {"share": round(all_right / n, 3), "ci95": wilson(all_right, n)}
        out["accuracy"][mode] = acc
    coop_calls = [r for r in rows if r["coop"]["in"]]
    for mode, calls, tin, tout in (
            ("aito_only", 0, 0, 0),
            ("aito_plus_llm", len(coop_calls), sum(r["coop"]["in"] for r in rows), sum(r["coop"]["out"] for r in rows)),
            ("llm_only", n, sum(r["llm_only"]["in"] for r in rows), sum(r["llm_only"]["out"] for r in rows))):
        out["llm"][mode] = {"calls_per_ticket": round(calls / n, 3), "tokens_per_ticket": round((tin + tout) / n),
                            "usd_per_1000_tickets": round(cost_usd(tin, tout) / n * 1000, 3)}
    pct = lambda xs, q: round(sorted(xs)[min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))])  # noqa: E731
    for mode, xs in (("aito_only", [r["aito_wall_ms"] for r in rows]),
                     ("aito_plus_llm", [r["aito_wall_ms"] + r["coop"]["ms"] for r in rows]),
                     ("llm_only", [r["llm_only"]["ms"] for r in rows])):
        out["latency_ms"][mode] = {"p50": pct(xs, 0.5), "p95": pct(xs, 0.95), "mean": round(st.mean(xs))}
    out["latency_ms"]["note"] = "LLM time is the successful call's own, excluding rate-limit backoff"
    unsure = [k for r in rows for k in r["coop"]["unsure"]]
    out["handed_to_llm"] = {k: sum(u == k for u in unsure) for k in TARGETS}
    out["selective"] = selective(rows)
    SUMMARY.write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    if "--summary" not in sys.argv:
        run()
    print(json.dumps(summarize(), indent=1))
