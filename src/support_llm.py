"""The LLM side of the support agent: one gpt-5-mini call that makes the ticket's
decisions, either all of them (LLM only) or just the ones Aito wasn't sure of,
choosing from Aito's shortlist (Aito + LLM).

The LLM sees what Aito sees at intake (the ticket text, the contact's role, the
account's plan and size) but not the desk's history: that knowledge is exactly
what Aito adds, so the comparison is fair.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from openai import BadRequestError

from src.llm_agent import cost_usd, get_agent

_SYSTEM = (
    "You are a B2B software support agent triaging an incoming ticket. For each decision asked, answer with "
    "exactly one of the allowed values, as JSON: {\"<decision>\": \"<value>\", ...}. Where options come with a "
    "probability from the company's history, weigh it, but choose what fits the ticket best. Answer only JSON."
)

#: what each decision means, for the prompt
DESCRIBE = {
    "product": "which product the ticket is about",
    "category": "the ticket's category",
    "priority": "its priority",
    "resolution": "how the desk should resolve it",
    "first_step": "the first action to take on it",
}


@dataclass
class LLMDecision:
    values: dict
    input_tokens: int
    output_tokens: int
    latency_ms: float

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.input_tokens, self.output_tokens)


def decide(ticket: dict, context: dict, options: dict[str, list[str]],
           shortlists: dict[str, list[tuple[str, float]]] | None = None,
           examples: list[str] | None = None, explanations: dict[str, str] | None = None) -> LLMDecision:
    """One call deciding every key of `options`. `shortlists` (Aito's top values
    with their $p) are offered first where given; the full option list stays
    available, so the LLM can overrule Aito. `examples` (RAG) are similar past
    tickets with how the desk decided them. `explanations` are Aito's reasons
    for its top value per decision (from $why)."""
    agent = get_agent()
    lines = [f"Ticket: {ticket['text']}", "Context: " + ", ".join(f"{k} {v}" for k, v in context.items() if v), ""]
    if examples:
        lines += ["Similar past tickets, and how this desk decided them:", *examples, ""]
    for key, allowed in options.items():
        lines.append(f"- {key} ({DESCRIBE.get(key, key)}); allowed: {', '.join(allowed)}")
        if shortlists and key in shortlists:
            lines.append("  history suggests: " + ", ".join(f"{v} ({p:.2f})" for v, p in shortlists[key]))
        if explanations and explanations.get(key):
            lines.append(f"  because: {explanations[key]}")
    base = {"model": agent._deployment, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "\n".join(lines)}]}
    sets = [agent._extra] if agent._extra is not None else agent._param_sets()
    last = None
    for extra in sets:
        try:
            resp, ms = agent._create(base, extra)
        except BadRequestError as e:
            last = e
            continue
        agent._extra = extra
        try:
            data = json.loads(resp.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            data = {}
        values = {k: (data.get(k) if data.get(k) in options[k] else None) for k in options}
        u = resp.usage
        return LLMDecision(values, int(u.prompt_tokens), int(u.completion_tokens), ms)
    raise RuntimeError(f"all param sets rejected: {last}")
