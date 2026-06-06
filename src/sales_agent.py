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

import json
import time
from typing import Any, Callable

from openai import BadRequestError

from src.llm_agent import cost_usd, get_agent

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


def _openai_tools(enabled: list[str]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["summary"],
                                              "parameters": t["parameters"]}}
            for t in TOOLS if t["name"] in enabled]


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


def _safe_args(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def run_turn(history: list[dict], tool_impls: dict[str, Callable[[dict], Any]],
             enabled: list[str], max_steps: int = 5) -> dict:
    """Run one assistant turn of the chat, executing any tool calls against the
    provided implementations.

    history: prior messages as [{role: 'user'|'assistant', content: str}, ...].
    Returns {reply, trace, steps, input_tokens, output_tokens, latency_ms, cost_usd}.
    `trace` is the list of tool calls made this turn (for the UI): each
    {name, op, aito, args, result, ms}.
    """
    agent = get_agent()
    msgs: list[dict] = [{"role": "system", "content": _SYSTEM}]
    msgs += [{"role": m["role"], "content": m.get("content", "")} for m in history]

    oai_tools = _openai_tools(enabled)
    trace: list[dict] = []
    in_tok = out_tok = 0
    llm_ms = 0.0

    for _ in range(max_steps):
        base: dict = {"model": agent._deployment, "messages": msgs}
        if oai_tools:
            base["tools"] = oai_tools
            base["tool_choice"] = "auto"

        # reuse llm_agent's param-set fallback (reasoning models reject temperature etc.)
        sets = [agent._extra] if agent._extra is not None else agent._param_sets()
        resp = ms = None
        last = None
        for extra in sets:
            ex = {k: v for k, v in extra.items() if k != "temperature"}  # tool calls + temperature can clash
            try:
                resp, ms = agent._create(base, ex)
            except BadRequestError as e:
                last = e
                continue
            agent._extra = extra
            break
        if resp is None:
            raise RuntimeError(f"all param sets rejected: {last}")

        llm_ms += ms
        if resp.usage:
            in_tok += int(resp.usage.prompt_tokens)
            out_tok += int(resp.usage.completion_tokens)

        choice = resp.choices[0].message
        calls = choice.tool_calls or []
        if not calls:
            return {
                "reply": choice.content or "",
                "trace": trace, "steps": len(trace),
                "input_tokens": in_tok, "output_tokens": out_tok,
                "latency_ms": round(llm_ms), "cost_usd": cost_usd(in_tok, out_tok),
            }

        # record the assistant's tool-call message, then run each tool
        msgs.append({
            "role": "assistant", "content": choice.content or "",
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls],
        })
        for c in calls:
            name = c.function.name
            args = _safe_args(c.function.arguments)
            impl = tool_impls.get(name)
            t0 = time.perf_counter()
            try:
                result = impl(args) if impl else {"error": f"tool '{name}' is not available"}
            except Exception as e:  # surface tool errors to the model instead of crashing the turn
                result = {"error": str(e)}
            dt = (time.perf_counter() - t0) * 1000
            spec = _BY_NAME.get(name, {})
            trace.append({"name": name, "op": spec.get("op", "?"), "aito": bool(spec.get("aito")),
                          "args": args, "result": result, "ms": round(dt)})
            msgs.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})

    # ran out of steps — ask for a plain summary with no more tools
    msgs.append({"role": "user", "content": "Wrap up now with your recommendation, no more tool calls."})
    final = agent._create({"model": agent._deployment, "messages": msgs},
                          {k: v for k, v in (agent._extra or {}).items() if k != "temperature"})[0]
    if final.usage:
        in_tok += int(final.usage.prompt_tokens)
        out_tok += int(final.usage.completion_tokens)
    return {
        "reply": final.choices[0].message.content or "",
        "trace": trace, "steps": len(trace),
        "input_tokens": in_tok, "output_tokens": out_tok,
        "latency_ms": round(llm_ms), "cost_usd": cost_usd(in_tok, out_tok),
    }
