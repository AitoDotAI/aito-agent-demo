"""Company AI agent — a 360° copilot over Northwind Cloud's own data.

A single `customers` master is linked to every domain (deals, tickets, usage,
invoices, feedback) and a `products` catalog, so the agent sees the whole company
and can OPTIMISE KPIs, not just report them:

  - kpi_snapshot  : the 360 card (conversion, churn, NPS, CSAT, adoption, on-time)
  - optimize_kpi  : drivers ($why) + the lever that moves a KPI + the projected lift
  - customer_360  : one customer across every domain (the linked join)
  - find_examples : ground an answer with real rows from any domain
  - estimate_mrr  : expected revenue for a segment
  - launch_play   : gated — drafts a play for a human to approve

A SQL+LLM BI bot can COUNT rows; this predicts, explains, and recommends — and
because Aito has no training step, a logged outcome is in the next prediction: a
closed optimise loop with no retrain.

Tool implementations live in app.py; the loop is agent_core.run_turn.
"""

from __future__ import annotations

from typing import Any, Callable

from src import agent_core

_INDUSTRY = ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"]
_SIZE = ["SMB", "Mid-market", "Enterprise"]
_PLAN = ["Free", "Starter", "Pro", "Enterprise"]
_SEATS = ["1-5", "6-20", "21-100", "100+"]
_KPI = ["conversion", "churn", "nps", "csat", "adoption", "ontime"]
_DOMAIN = ["customers", "deals", "tickets", "usage", "invoices", "feedback"]


def _enum(desc: str, values: list[str]) -> dict:
    return {"type": "string", "description": desc, "enum": values}


# a reusable customer-segment block (industry/size/plan) most tools accept
_SEG = {
    "industry": _enum("Customer industry", _INDUSTRY),
    "size": _enum("Customer size", _SIZE),
    "plan": _enum("Subscription plan", _PLAN),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "kpi_snapshot",
        "aito": True, "op": "_predict",
        "summary": "The 360 KPI card for a customer segment: conversion, churn, NPS, CSAT, adoption, on-time revenue.",
        "parameters": {"type": "object", "properties": {**_SEG}, "additionalProperties": False},
    },
    {
        "name": "optimize_kpi",
        "aito": True, "op": "_predict · _relate · _recommend",
        "summary": "For a KPI + segment: the root causes (drivers), the lever values most tied to success, and the projected lift.",
        "parameters": {"type": "object", "properties": {
            "kpi": _enum("Which KPI to optimise", _KPI), **_SEG,
        }, "required": ["kpi"], "additionalProperties": False},
    },
    {
        "name": "customer_360",
        "aito": True, "op": "_query",
        "summary": "One customer across every domain — profile, deals, tickets, product usage, invoices, feedback.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "e.g. ACC-123456 (get one from find_examples)"},
        }, "required": ["customer_id"], "additionalProperties": False},
    },
    {
        "name": "find_examples",
        "aito": True, "op": "_query",
        "summary": "Example rows from any domain (use domain='customers' to get customer_ids to drill into).",
        "parameters": {"type": "object", "properties": {
            "domain": _enum("Which table to sample", _DOMAIN), **_SEG,
            "churned": {"type": "string", "description": "customers only: filter by churn", "enum": ["yes", "no"]},
        }, "required": ["domain"], "additionalProperties": False},
    },
    {
        "name": "estimate_mrr",
        "aito": True, "op": "_estimate",
        "summary": "Expected monthly recurring revenue (EUR) for a customer segment.",
        "parameters": {"type": "object", "properties": {**_SEG, "seats_band": _enum("Seat band", _SEATS)},
                       "additionalProperties": False},
    },
    {
        "name": "launch_play",
        "aito": False, "op": "action",
        "summary": "Draft a play to move a KPI (e.g. switch a segment to a CSM motion) — for a human to approve; never runs on its own.",
        "parameters": {"type": "object", "properties": {
            "kpi": _enum("KPI the play targets", _KPI),
            "segment": {"type": "string", "description": "Who it applies to"},
            "play": {"type": "string", "description": "The lever change / action"},
            "expected_impact": {"type": "string", "description": "Projected effect, from the data"},
        }, "required": ["play"], "additionalProperties": False},
    },
]

AITO_TOOL_NAMES = [t["name"] for t in TOOLS if t["aito"]]


def tools_public() -> list[dict]:
    return [{"name": t["name"], "op": t["op"], "aito": t["aito"], "summary": t["summary"],
             "params": list(t["parameters"]["properties"].keys())} for t in TOOLS]


_SYSTEM = (
    "You are the Company AI copilot for Northwind Cloud, a B2B SaaS company. You have a 360° view of its own data: "
    "a single customers master linked to deals (sales), tickets (support), usage (product), invoices (finance) and "
    "feedback (CX). You help staff understand AND IMPROVE the KPIs: conversion, churn, NPS, CSAT, adoption, on-time "
    "revenue.\n\n"
    "You can't run arbitrary SQL — lean into what you CAN do, via tools that read the real data: kpi_snapshot (the "
    "360 card for a segment), optimize_kpi (a KPI's drivers + the lever that moves it most + the projected lift), "
    "customer_360 (one customer across every domain), find_examples (ground with real rows / get customer_ids), "
    "estimate_mrr. Whenever a claim depends on a number, CALL THE TOOL — don't guess. Map what the user described "
    "into the segment fields. If a needed tool isn't available, say so and label any guess as unverified.\n\n"
    "Frame answers as an operator who optimises outcomes: quote the current KPI, the driver, the recommended lever "
    "change and its projected lift (e.g. 'churn 84% → 74% if moved to a Dedicated CSM'). When you propose acting, "
    "call launch_play — it only DRAFTS a play for a human to approve; never claim anything ran. And note the loop: "
    "Aito has no training step, so once a play's outcome is logged it sharpens the next prediction — optimise, act, "
    "learn, with no retrain.\n\n"
    "Be concise and concrete, like a sharp RevOps analyst."
)


def run_turn(history: list[dict], tool_impls: dict[str, Callable[[dict], Any]],
             enabled: list[str], max_steps: int = 6) -> dict:
    return agent_core.run_turn(history, _SYSTEM, TOOLS, tool_impls, enabled, max_steps)
