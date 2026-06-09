"""A live, conversational sales agent — gpt-5-mini with a tool-calling loop.

The point of this module is the demo's thesis made concrete: **Aito is a tool
in the agent's toolbox**, not a thing that replaces the agent. The LLM does the
reasoning and the talking; when it needs a number it can't invent — win odds,
effort, references, the best way in — it *calls an Aito op*. The same agent run
with the Aito tools removed has to guess (and is told to flag the guess), which
is the whole augment-vs-replace contrast in one toggle.

Layering:
  - This module owns the LLM loop + the tool *catalog* (names, descriptions,
    JSON schemas, which op backs each). It is pure orchestration — it never
    touches Aito directly.
  - app.py owns the tool *implementations* (they call the shared AitoClient) and
    passes them in as a {name: callable} dict. That keeps the Aito wiring next
    to the other routes and this file free of a circular import.

Reuses the Azure client + retry/param-fallback from llm_agent.get_agent().
"""

from __future__ import annotations

from typing import Any, Callable

from src import agent_core

# ── vocab (mirrors scripts/seed_sales.py so tool args land on real values) ──
_INDUSTRY = ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"]
_SIZE = ["SMB", "Mid-market", "Enterprise"]
_SERVICE = ["Advisory", "Analytics & ML", "Integration", "Data Platform", "Cloud Migration", "Custom Dev"]
_BAND = ["S", "M", "L", "XL"]
_LEAD = ["Referral", "Partner", "Inbound", "Event", "Outbound"]
_REL = ["New logo", "Existing client"]
_COMP = ["Sole-source", "Competitive"]
_CPX = ["Low", "Medium", "High"]
_SEN = ["junior-heavy", "balanced", "senior-heavy"]
_ROLE = ["CTO", "Head of Data", "COO", "CEO", "Procurement"]


def _enum(desc: str, values: list[str]) -> dict:
    return {"type": "string", "description": desc, "enum": values}


# ── the toolbox ────────────────────────────────────────────────────────────
# Each entry: the OpenAI function schema + metadata (which Aito op backs it).
# `aito` flags the four tools the on/off toggle removes; propose_send_email is a
# plain action that is always present (and never actually sends — it queues a
# draft for human approval, honouring the "no auto-fired actions" rule).

TOOLS: list[dict[str, Any]] = [
    {
        "name": "win_odds",
        "aito": True,
        "op": "_predict",
        "summary": "Probability this opportunity is won, with the drivers behind it.",
        "parameters": {
            "type": "object",
            "properties": {
                "industry": _enum("Client industry", _INDUSTRY),
                "client_size": _enum("Client size", _SIZE),
                "service_line": _enum("Service line", _SERVICE),
                "deal_size_band": _enum("Deal size band (S<50k, M 50-150k, L 150-400k, XL>400k)", _BAND),
                "lead_source": _enum("How the lead arrived", _LEAD),
                "relationship": _enum("New logo or existing client", _REL),
                "competitive": _enum("Sole-source or competitive", _COMP),
                "complexity": _enum("Delivery complexity", _CPX),
                "team_seniority": _enum("Proposed team mix", _SEN),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "estimate_effort",
        "aito": True,
        "op": "_estimate",
        "summary": "Estimated effort in person-days from similar past engagements.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_line": _enum("Service line", _SERVICE),
                "deal_size_band": _enum("Deal size band", _BAND),
                "complexity": _enum("Delivery complexity", _CPX),
                "team_seniority": _enum("Proposed team mix", _SEN),
                "industry": _enum("Client industry", _INDUSTRY),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "find_references",
        "aito": True,
        "op": "_query",
        "summary": "Past *won* engagements in this segment, to cite as references.",
        "parameters": {
            "type": "object",
            "properties": {
                "industry": _enum("Client industry", _INDUSTRY),
                "service_line": _enum("Service line", _SERVICE),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "recommend_outreach",
        "aito": True,
        "op": "_recommend",
        "summary": "The channel + angle most likely to land a meeting, and the predicted meeting rate.",
        "parameters": {
            "type": "object",
            "properties": {
                "industry": _enum("Target industry", _INDUSTRY),
                "target_role": _enum("Who you'd contact", _ROLE),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_send_email",
        "aito": False,
        "op": "action",
        "summary": "Queue an outreach email as a DRAFT for the rep to approve — never sends on its own.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient (name/role/company is fine)"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "The email body you drafted"},
            },
            "required": ["subject", "body"],
            "additionalProperties": False,
        },
    },
]

_BY_NAME = {t["name"]: t for t in TOOLS}
AITO_TOOL_NAMES = [t["name"] for t in TOOLS if t["aito"]]


def tools_public() -> list[dict]:
    """Toolbox metadata for the frontend (no JSON-schema noise)."""
    return [{"name": t["name"], "op": t["op"], "aito": t["aito"], "summary": t["summary"],
             "params": list(t["parameters"]["properties"].keys())} for t in TOOLS]


_SYSTEM = (
    "You are the opportunity assistant for Northlight Consulting, a B2B consulting firm. "
    "You help a sales rep decide whether to pursue an opportunity and how to approach it, in a short chat.\n\n"
    "You have tools that read Northlight's OWN history and return real, calibrated numbers: win odds (with the "
    "drivers behind them), an effort estimate, reference projects, and the outreach most likely to land. "
    "Whenever a claim depends on such a number, CALL THE TOOL rather than guessing — map what you know from the "
    "conversation into the tool's fields (leave a field out if the rep hasn't said). You may call several tools.\n\n"
    "If a tool you need is NOT in your toolbox, do not pretend: give your best rough estimate but clearly label it "
    "an unverified guess (e.g. 'rough guess, not from our data') and say which tool you'd want.\n\n"
    "These tools don't just inform — they OPTIMISE the outcome. recommend_outreach picks the approach that books "
    "the most meetings and returns the lift over the unoptimised baseline; when you recommend it, quote BOTH the "
    "expected meeting rate and that lift (e.g. '~59% vs ~16% baseline — about 3.7x more meetings'). Likewise, frame "
    "win odds + effort as a pursue/scope decision (chase winners, protect margin), not just a number.\n\n"
    "Be concise and concrete. When you draft an outreach email, call propose_send_email — it only queues a DRAFT "
    "for the rep to approve; never claim an email was actually sent. Quote the figures the tools returned."
)


def run_turn(history: list[dict], tool_impls: dict[str, Callable[[dict], Any]],
             enabled: list[str], max_steps: int = 5) -> dict:
    """One assistant turn — delegates to the shared agent loop with this agent's
    system prompt + tool catalog."""
    return agent_core.run_turn(history, _SYSTEM, TOOLS, tool_impls, enabled, max_steps)
