"""Governance: the rules the agent's logged decisions follow (use case #15).

Mines candidate rules from a decision log with `_relate`, one call per decision
value, and ranks them for a reviewer. Each rule is in the shape of the
accounting demo's promote API (aito-accounting-demo ADR 0025), so promoting one
later is a write of this same object:

    {"rule": {"conditions": [{"field", "op", "value"}], "target": {"field", "value"}},
     "support": {"match", "total"}, "precision", "coverage", "strength"}

For a rule "condition -> target": `support.total` is how many logged decisions
the condition fires on, `support.match` how many of those the target was the
decision, `precision` = match / total, and `coverage` = match / all decisions
of that target. Read-only: nothing here writes, and a rule that holds on the
log may still hold only by accident of how the log was written, which is what
the review is for.
"""

from __future__ import annotations

from src.aito_client import AitoClient

#: Decision logs the demo governs: the log table, the decision field, and the
#: inputs a rule may condition on.
LOGS = {
    "resolutions": {"target": "intent", "inputs": ["text", "sender_domain", "customer"],
                    "label": "ticket resolutions"},
    "tool_calls": {"target": "tool", "inputs": ["text"], "label": "tool routing"},
}

#: A candidate must be right this often when it fires; below it, a condition is a
#: common word or value, not a rule.
MIN_PRECISION = 0.8
#: Strong enough to promote: right at least this often, on at least this many decisions.
STRONG_PRECISION = 0.95
STRONG_MATCH = 20


def _conditions(related: dict) -> list[dict]:
    """{"text": {"$has": "refund"}} (v1 and v2 for Text) or {"customer": "acme"} (v2 bare)
    -> [{"field", "op", "value"}]."""
    out = []
    for field, cond in related.items():
        if isinstance(cond, dict):
            for op, value in cond.items():
                out.append({"field": field, "op": op.lstrip("$"), "value": value})
        else:
            out.append({"field": field, "op": "is", "value": cond})
    return out


def rule_from_hit(hit: dict, target_field: str, target_value) -> dict | None:
    fs = hit.get("fs") or {}
    total, match, of_target = fs.get("f") or 0, fs.get("fOnCondition") or 0, fs.get("fCondition") or 0
    conditions = _conditions(hit.get("related") or {})
    if not total or not conditions:
        return None
    precision, coverage = match / total, (match / of_target if of_target else 0.0)
    strong = precision >= STRONG_PRECISION and match >= STRONG_MATCH
    return {
        "rule": {"conditions": conditions, "target": {"field": target_field, "value": target_value}},
        "support": {"match": int(match), "total": int(total)},
        "precision": round(precision, 3),
        "coverage": round(coverage, 3),
        "strength": "strong" if strong else "candidate",
    }


def mine_rules(aito: AitoClient, log: str, per_value: int = 20) -> dict:
    """Candidate rules over one decision log, strongest first (precision x coverage)."""
    cfg = LOGS[log]
    target = cfg["target"]
    rows = aito.query(log, select=[target], limit=10000).get("hits") or []
    values = sorted({r.get(target) for r in rows} - {None})
    rules = []
    for v in values:
        hits = aito.relate(log, {target: v}, cfg["inputs"], limit=per_value).get("hits") or []
        for h in hits:
            r = rule_from_hit(h, target, v)
            if r and r["precision"] >= MIN_PRECISION:
                rules.append(r)
    rules.sort(key=lambda r: -(r["precision"] * r["coverage"]))
    return {
        "log": log, "label": cfg["label"], "target": target, "decisions": len(rows),
        "decision_values": len(values), "rules": rules,
        "strong": sum(r["strength"] == "strong" for r in rules),
        "thresholds": {"min_precision": MIN_PRECISION, "strong_precision": STRONG_PRECISION,
                       "strong_match": STRONG_MATCH},
    }
