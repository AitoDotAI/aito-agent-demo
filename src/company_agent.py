"""Company AI agent — gpt-5-mini that answers questions about the company's own
numbers by calling Aito ops as tools.

The point: a SQL+LLM "BI chatbot" can COUNT rows. It can't tell you which accounts
will churn and WHY, what's dragging NPS in a segment, the expected MRR of a cohort,
or which feedback themes to fix — calibrated, with drivers, no training. Those are
_predict / _estimate / _recommend / _query, registered here as tools.

Tool *implementations* live in app.py (they call the shared AitoClient over the
`accounts` + `feedback` tables); the loop is agent_core.run_turn.
"""

from __future__ import annotations

from typing import Any, Callable

from src import agent_core

# ── vocab (mirrors scripts/seed_company.py so tool args hit real values) ──
_INDUSTRY = ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"]
_SIZE = ["SMB", "Mid-market", "Enterprise"]
_PLAN = ["Free", "Starter", "Pro", "Enterprise"]
_TENURE = ["<3mo", "3-12mo", "1-2y", "2y+"]
_SEATS = ["1-5", "6-20", "21-100", "100+"]
_ONBOARDING = ["Completed", "Partial", "None"]
_SUPPORT = ["none", "low", "high"]
_USAGE = ["low", "medium", "high"]
_HEALTH = ["Green", "Yellow", "Red"]
_NPS = ["promoter", "passive", "detractor"]
_SURVEY = ["NPS", "CSAT", "CES"]


def _enum(desc: str, values: list[str]) -> dict:
    return {"type": "string", "description": desc, "enum": values}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "churn_risk",
        "aito": True, "op": "_predict",
        "summary": "Probability an account (or segment) churns, with the drivers behind it.",
        "parameters": {"type": "object", "properties": {
            "industry": _enum("Account industry", _INDUSTRY),
            "size": _enum("Account size", _SIZE),
            "plan": _enum("Subscription plan", _PLAN),
            "tenure_band": _enum("How long they've been a customer", _TENURE),
            "onboarding": _enum("Onboarding status", _ONBOARDING),
            "support_load": _enum("Support ticket load", _SUPPORT),
            "usage": _enum("Product usage level", _USAGE),
            "health": _enum("CS health flag", _HEALTH),
            "nps_band": _enum("Latest NPS band", _NPS),
        }, "additionalProperties": False},
    },
    {
        "name": "nps_drivers",
        "aito": True, "op": "_predict",
        "summary": "For a segment, the chance feedback is a detractor and the themes/factors driving it.",
        "parameters": {"type": "object", "properties": {
            "industry": _enum("Account industry", _INDUSTRY),
            "size": _enum("Account size", _SIZE),
            "plan": _enum("Subscription plan", _PLAN),
            "survey_type": _enum("Survey type", _SURVEY),
        }, "additionalProperties": False},
    },
    {
        "name": "estimate_mrr",
        "aito": True, "op": "_estimate",
        "summary": "Expected monthly recurring revenue (EUR) for a segment of accounts.",
        "parameters": {"type": "object", "properties": {
            "plan": _enum("Subscription plan", _PLAN),
            "size": _enum("Account size", _SIZE),
            "seats_band": _enum("Seat count band", _SEATS),
            "industry": _enum("Account industry", _INDUSTRY),
        }, "additionalProperties": False},
    },
    {
        "name": "find_accounts",
        "aito": True, "op": "_query",
        "summary": "Pull example accounts matching a filter (to ground the answer with real rows).",
        "parameters": {"type": "object", "properties": {
            "industry": _enum("Account industry", _INDUSTRY),
            "size": _enum("Account size", _SIZE),
            "plan": _enum("Subscription plan", _PLAN),
            "health": _enum("CS health flag", _HEALTH),
            "churned": {"type": "string", "description": "Filter by churn", "enum": ["yes", "no"]},
        }, "additionalProperties": False},
    },
    {
        "name": "recommend_focus",
        "aito": True, "op": "_recommend",
        "summary": "Which feedback themes to prioritise for a segment to move accounts toward promoter.",
        "parameters": {"type": "object", "properties": {
            "industry": _enum("Account industry", _INDUSTRY),
            "size": _enum("Account size", _SIZE),
            "plan": _enum("Subscription plan", _PLAN),
        }, "additionalProperties": False},
    },
    {
        "name": "open_cs_task",
        "aito": False, "op": "action",
        "summary": "Open a customer-success task as a DRAFT for a human to approve — never acts on its own.",
        "parameters": {"type": "object", "properties": {
            "account": {"type": "string", "description": "Account name/id/segment"},
            "title": {"type": "string"},
            "notes": {"type": "string", "description": "What to do and why"},
        }, "required": ["title", "notes"], "additionalProperties": False},
    },
]

AITO_TOOL_NAMES = [t["name"] for t in TOOLS if t["aito"]]


def tools_public() -> list[dict]:
    return [{"name": t["name"], "op": t["op"], "aito": t["aito"], "summary": t["summary"],
             "params": list(t["parameters"]["properties"].keys())} for t in TOOLS]


_SYSTEM = (
    "You are the Company AI analyst for Northwind Cloud, a B2B SaaS company. You help staff understand the "
    "company's OWN numbers in a short chat — churn risk, what drives NPS, expected revenue, which accounts are "
    "at risk, what to do about it.\n\n"
    "You have tools that read Northwind's data and return real, calibrated answers: churn probability with its "
    "drivers, NPS/detractor drivers, an MRR estimate, example accounts, and the feedback themes to prioritise. "
    "Whenever a claim depends on such a number, CALL THE TOOL rather than guessing — map what the user described "
    "into the tool's fields (leave a field out if unknown). You may call several tools.\n\n"
    "You are NOT a SQL database — you can't do arbitrary group-by counts. Lean into what you CAN do: predict, "
    "explain the drivers, estimate, and recommend. Use find_accounts to ground an answer with example rows. If a "
    "needed tool isn't in your toolbox, don't pretend — give a best-effort guess clearly labelled as unverified "
    "and name the tool you'd want.\n\n"
    "Be concise and concrete, like a sharp analyst. Quote the figures and the drivers the tools returned, and turn "
    "them into a recommendation. When you propose an intervention, call open_cs_task — it only DRAFTS a task for a "
    "human to approve; never claim anything was actually done."
)


def run_turn(history: list[dict], tool_impls: dict[str, Callable[[dict], Any]],
             enabled: list[str], max_steps: int = 5) -> dict:
    """One assistant turn — delegates to the shared agent loop."""
    return agent_core.run_turn(history, _SYSTEM, TOOLS, tool_impls, enabled, max_steps)
