"""The support agent's predictive envelope (docs/design/support-agent.md, phase 1).

One incoming ticket, the steps a support agent takes, and the Aito op that
grounds each step. Read-only: tickets come from the held-out incoming queue
(src/data/support_incoming.json), which is never loaded into Aito, so every
prediction is on a ticket Aito has not seen and can be compared with the
ticket's recorded truth.

Every prediction goes through `guarded()`, which enforces the fixture's
inputs-vs-targets table (scripts/support_fixture/README.md) in code: a step
may use only the inputs listed for its target, so a column that is recorded
later, or that gives the answer away, cannot leak into a prediction. The
lists are allow-lists: a field not named is refused, not trusted.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.aito_client import AitoClient

INCOMING = Path(__file__).resolve().parent / "data" / "support_incoming.json"

#: What a ticket carries at intake, before anyone has worked on it.
INTAKE = {"text", "sender_domain", "channel", "month", "customer", "product", "adoption_band", "repeat_30d"}
#: Linked fields are allowed through these links (customer.plan, product.tier, ...).
LINKS = ("customer.", "product.")

#: target (table, field) -> the inputs it may use. Anything else refuses.
ALLOWED: dict[tuple[str, str], set[str]] = {
    ("support_tickets", "customer"): {"text", "sender_domain"},
    ("support_tickets", "category"): INTAKE,
    ("support_tickets", "priority"): INTAKE | {"category"},
    ("support_tickets", "resolution"): INTAKE | {"category"},
    ("support_tickets", "kb_article"): INTAKE | {"category"},
    ("support_tickets", "nps_after"): INTAKE | {"category", "priority", "recovery", "first_response"},
    ("support_tickets", "upsell_accepted"): {"adoption_band", "customer", "product", "upsell_offered"},
    ("support_steps", "action"): {"previous_action", "category", "step_no", "ticket.issue", "ticket.category",
                                  "ticket.priority", "ticket.customer"},
}
#: filters a target must carry: an upsell is only accepted or not when it was offered
REQUIRED: dict[tuple[str, str], dict] = {
    ("support_tickets", "upsell_accepted"): {"upsell_offered": "yes"},
}


class LeakError(ValueError):
    """A prediction asked for an input its target may not use."""


def _allowed(field: str, allowed: set[str]) -> bool:
    if field in allowed:
        return True
    # a linked attribute is allowed when its link is: customer.plan via "customer"
    head = field.split(".", 1)[0]
    return (field.startswith(LINKS) and head in allowed) or \
        (field.startswith("ticket.customer.") and "ticket.customer" in allowed)


def check_inputs(table: str, target: str, where: dict) -> None:
    key = (table, target)
    if key not in ALLOWED:
        raise LeakError(f"no input list for {table}.{target}: add one before predicting it")
    bad = sorted(f for f in where if not _allowed(f, ALLOWED[key]))
    if bad:
        raise LeakError(f"{table}.{target} may not use {bad} as input (see the inputs-vs-targets table)")
    for f, v in REQUIRED.get(key, {}).items():
        if where.get(f) != v:
            raise LeakError(f"{table}.{target} must be predicted with {f} = {v!r}")


def guarded(aito: AitoClient, table: str, where: dict, target: str, limit: int = 3) -> dict:
    """_predict through the leak guard; returns the top value, its $p, the runners-up and the latency."""
    check_inputs(table, target, where)
    t0 = time.perf_counter()
    r = aito.predict(table, where, target, limit=limit, select=["$p", "feature"])
    hits = r.get("hits") or []
    return {"value": hits[0].get("feature") if hits else None,
            "p": round(float(hits[0]["$p"]), 3) if hits else None,
            "alternatives": [{"value": h.get("feature"), "p": round(float(h["$p"]), 3)} for h in hits[1:]],
            "inputs": sorted(where), "ms": round((time.perf_counter() - t0) * 1000)}


def guarded_recommend(aito: AitoClient, table: str, where: dict, field: str, goal: dict, limit: int = 4) -> dict:
    """_recommend through the same guard: the goal is the target, so the context
    AND the recommended field must both be inputs that target may use."""
    (target,) = goal
    check_inputs(table, target, {**where, field: None})
    t0 = time.perf_counter()
    hits = aito.recommend(table, where, field, goal, limit=limit).get("hits") or []
    return {"value": hits[0].get("feature") if hits else None,
            "p": round(float(hits[0]["$p"]), 3) if hits else None,
            "alternatives": [{"value": h.get("feature"), "p": round(float(h["$p"]), 3)} for h in hits[1:]],
            "inputs": sorted(where), "ms": round((time.perf_counter() - t0) * 1000)}


def load_incoming(path: Path = INCOMING) -> dict:
    held = json.loads(path.read_text())
    steps: dict[str, list[dict]] = {}
    for s in held["steps"]:
        steps.setdefault(s["ticket"], []).append(s)
    return {"tickets": {t["ticket_id"]: t for t in held["tickets"]},
            "order": [t["ticket_id"] for t in held["tickets"]],
            "steps": {k: sorted(v, key=lambda s: s["step_no"]) for k, v in steps.items()}}


#: $p at or above this is served from history; the demo's existing gates (app.py)
AUTO, ASSIST = 0.85, 0.65


def _gate(p: float | None) -> str:
    return "auto" if p is not None and p >= AUTO else ("assist" if p is not None and p >= ASSIST else "human")


def envelope(aito: AitoClient, ticket: dict, true_steps: list[dict]) -> dict:
    """Run every step for one incoming ticket. Truth is attached per step for the
    view to compare with, never passed to a prediction."""
    intake = {k: ticket[k] for k in ("text", "sender_domain", "channel", "month", "adoption_band", "repeat_30d")}
    steps = []

    def add(key, title, op, result, truth=None, note=None):
        steps.append({"key": key, "title": title, "op": op, **result,
                      "truth": truth, "correct": (result.get("value") == truth) if truth is not None else None,
                      "note": note})

    who = guarded(aito, "support_tickets", {"text": ticket["text"], "sender_domain": ticket["sender_domain"]}, "customer")
    add("customer", "Who is this?", "_predict customer", who, ticket["customer"],
        note="the agent confirms the account before going on, so later steps use the confirmed one")
    known = {**intake, "customer": ticket["customer"], "product": ticket["product"]}  # the account, once confirmed

    cat = guarded(aito, "support_tickets", known, "category")
    add("category", "What is it about?", "_predict category", cat, ticket["category"])
    pri = guarded(aito, "support_tickets", {**known, "category": cat["value"]}, "priority")
    add("priority", "How urgent?", "_predict priority", pri, ticket["priority"])

    res = guarded(aito, "support_tickets", {**known, "category": cat["value"]}, "resolution")
    gate = _gate(res["p"])
    add("resolution", "Decide from history, or ask the LLM?", "_predict resolution  ·  $p gate", res,
        ticket["resolution"])
    steps[-1]["gate"] = gate

    kb = guarded(aito, "support_tickets", {**known, "category": cat["value"]}, "kb_article")
    add("kb", "Which article helps?", "_predict kb_article", kb, ticket["kb_article"])

    t0 = time.perf_counter()
    similar = aito.query("support_tickets", select=["ticket_id", "text", "resolution", "nps_after"],
                         order_by={"$similarity": {"text": ticket["text"]}}, limit=3).get("hits") or []
    add("similar", "How were tickets like this solved?", "_query orderBy $similarity",
        {"value": None, "p": None, "alternatives": [], "inputs": ["text"], "ms": round((time.perf_counter() - t0) * 1000),
         "cases": similar})

    # the first step of the fix, and what follows it, from the step log
    first = guarded(aito, "support_steps", {"previous_action": "start", "category": cat["value"]}, "action")
    add("first_step", "Where to start?", "_predict next action", first,
        true_steps[0]["action"] if true_steps else None)

    risk = guarded(aito, "support_tickets", {**known, "category": cat["value"], "priority": pri["value"]}, "nps_after")
    add("risk", "Will this customer turn detractor?", "_predict nps_after", risk, ticket["nps_after"],
        note="recorded after the ticket; compared, never used as an input")
    rec = guarded_recommend(aito, "support_tickets", {"customer": ticket["customer"], "repeat_30d": ticket["repeat_30d"]},
                            "recovery", {"nps_after": "promoter"})
    add("recovery", "What protects the relationship?", "_recommend recovery → promoter", rec,
        note="the recovery in the log was assigned at random, so its effect is causal")

    ups = guarded(aito, "support_tickets", {"adoption_band": ticket["adoption_band"], "customer": ticket["customer"],
                                            "upsell_offered": "yes"}, "upsell_accepted")
    add("upsell", "Is an upsell welcome?", "_predict upsell_accepted", ups, ticket["upsell_accepted"],
        note=None if ticket["upsell_offered"] == "yes" else "no offer was made on this ticket; nothing to compare")

    return {"ticket": {k: ticket[k] for k in ("ticket_id", "created_at", "text", "sender_domain", "channel")},
            "steps": steps, "gate": gate,
            "aito_calls": len(steps), "aito_ms": sum(s["ms"] for s in steps)}
