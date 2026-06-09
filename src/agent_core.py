"""Shared tool-calling loop for the demo's conversational agents.

Both the sales agent and the company agent are the same machine: a gpt-5-mini
chat that calls Aito ops as tools. This module owns that loop so each agent file
only declares its own tool catalog + system prompt + tool implementations.

Reuses the Azure client + retry/param-fallback from llm_agent.get_agent().
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from openai import BadRequestError

from src.llm_agent import cost_usd, get_agent


def openai_tools(tools: list[dict], enabled: list[str]) -> list[dict]:
    """Build the OpenAI `tools` array from a tool catalog, filtered to enabled."""
    return [{"type": "function", "function": {"name": t["name"], "description": t["summary"],
                                              "parameters": t["parameters"]}}
            for t in tools if t["name"] in enabled]


def _safe_args(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def run_turn(history: list[dict], system: str, tools: list[dict],
             tool_impls: dict[str, Callable[[dict], Any]], enabled: list[str],
             max_steps: int = 5) -> dict:
    """Run one assistant turn, executing any tool calls against tool_impls.

    Returns {reply, trace, steps, input_tokens, output_tokens, latency_ms, cost_usd}.
    `trace` is the tool calls made this turn: each {name, op, aito, args, result, ms}.
    """
    agent = get_agent()
    by_name = {t["name"]: t for t in tools}
    msgs: list[dict] = [{"role": "system", "content": system}]
    msgs += [{"role": m["role"], "content": m.get("content", "")} for m in history]

    oai_tools = openai_tools(tools, enabled)
    trace: list[dict] = []
    in_tok = out_tok = 0
    llm_ms = 0.0

    for _ in range(max_steps):
        base: dict = {"model": agent._deployment, "messages": msgs}
        if oai_tools:
            base["tools"] = oai_tools
            base["tool_choice"] = "auto"

        sets = [agent._extra] if agent._extra is not None else agent._param_sets()
        resp = ms = None
        last = None
        for extra in sets:
            ex = {k: v for k, v in extra.items() if k != "temperature"}  # tool calls + temperature clash
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
            return {"reply": choice.content or "", "trace": trace, "steps": len(trace),
                    "input_tokens": in_tok, "output_tokens": out_tok,
                    "latency_ms": round(llm_ms), "cost_usd": cost_usd(in_tok, out_tok)}

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
            except Exception as e:  # surface tool errors to the model, don't crash the turn
                result = {"error": str(e)}
            dt = (time.perf_counter() - t0) * 1000
            spec = by_name.get(name, {})
            trace.append({"name": name, "op": spec.get("op", "?"), "aito": bool(spec.get("aito")),
                          "args": args, "result": result, "ms": round(dt)})
            msgs.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})

    # ran out of steps — force a plain wrap-up with no more tools
    msgs.append({"role": "user", "content": "Wrap up now with your answer, no more tool calls."})
    final = agent._create({"model": agent._deployment, "messages": msgs},
                          {k: v for k, v in (agent._extra or {}).items() if k != "temperature"})[0]
    if final.usage:
        in_tok += int(final.usage.prompt_tokens)
        out_tok += int(final.usage.completion_tokens)
    return {"reply": final.choices[0].message.content or "", "trace": trace, "steps": len(trace),
            "input_tokens": in_tok, "output_tokens": out_tok,
            "latency_ms": round(llm_ms), "cost_usd": cost_usd(in_tok, out_tok)}
