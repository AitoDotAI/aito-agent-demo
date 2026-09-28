"""Shared tool-calling loop for the demo's conversational agents.

Both the sales agent and the company agent are the same machine: a gpt-5-mini
chat that calls Aito ops as tools. This module owns that loop so each agent file
only declares its own tool catalog + system prompt + tool implementations.

Reuses the Azure client + retry/param-fallback from llm_agent.get_agent().
"""

from __future__ import annotations

import json
import re
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


def plain_dashes(text: str) -> str:
    """User-facing copy uses no em-dashes; the model still writes some despite the
    prompt. A spaced one reads as a comma, an unspaced one as a hyphen."""
    return re.sub(r"\s*—\s*", ", ", re.sub(r"(?<=\w)—(?=\w)", "-", text or ""))


# A percentage ("~70%") or a multiplier ("3.7x", "3.7×"): the figures a draft must not invent.
_FIGURE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|[x×](?!\w))", re.I)


def _known_figures(values: Any, out: set[float]) -> set[float]:
    """Every number a source holds; a probability also counts as its percentage."""
    if isinstance(values, dict):
        for v in values.values():
            _known_figures(v, out)
    elif isinstance(values, list):
        for v in values:
            _known_figures(v, out)
    elif isinstance(values, (int, float)) and not isinstance(values, bool):
        out.add(float(values))
        if 0 <= values <= 1:
            out.add(float(values) * 100)
    elif isinstance(values, str):
        out |= {float(x) for x in re.findall(r"\d+(?:\.\d+)?", values)}
    return out


def ungrounded_figures(draft: dict, trace: list[dict], history: list[dict]) -> list[str]:
    """Percentages / multipliers in a draft that no tool returned this turn and no
    earlier message stated. Earlier turns' tool results only survive as the
    assistant's own quoted text, so that text counts as a source too. A figure
    matches a source number when it is that number rounded (59% for 0.587)."""
    known: set[float] = set()
    _known_figures([t["result"] for t in trace], known)
    _known_figures([m.get("content", "") for m in history], known)
    text = " ".join(v for v in draft.values() if isinstance(v, str))
    return [m.group(0) for m in _FIGURE.finditer(text)
            if not any(abs(float(m.group(1)) - k) <= 0.5 for k in known)]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _said(value: str, heard: set[str]) -> bool:
    """Every word of an enum value was said, allowing inflection ("bank" for
    "Banking", "custom-dev" for "Custom Dev") by a shared 4+ letter stem."""
    def one(w: str) -> bool:
        return w in heard or (len(w) >= 4 and any(len(h) >= 4 and (h.startswith(w[:5]) or w.startswith(h[:5]))
                                                   for h in heard))
    return all(one(w) for w in _words(value))


def unstated_args(args: dict, spec: dict, trace: list[dict], history: list[dict]) -> dict:
    """The enum arguments whose value the user never said and no tool returned:
    the model filled them in. Free-text arguments are not checked."""
    heard = _words(" ".join(m.get("content", "") for m in history if m.get("role") == "user"))
    heard |= _words(json.dumps([t["result"] for t in trace]))
    props = spec.get("parameters", {}).get("properties", {})
    return {k: v for k, v in args.items()
            if isinstance(v, str) and "enum" in props.get(k, {}) and not _said(v, heard)}


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
            return {"reply": plain_dashes(choice.content), "trace": trace, "steps": len(trace),
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
            spec = by_name.get(name, {})
            if spec.get("grounded_figures"):
                args = {k: plain_dashes(v) if isinstance(v, str) else v for k, v in args.items()}
                bad = ungrounded_figures(args, trace, history)
            else:
                bad = []
            dropped = unstated_args(args, spec, trace, history) if spec.get("grounded_args") else {}
            if dropped:  # answer from what the user said; tell the model what it filled in
                args = {k: v for k, v in args.items() if k not in dropped}
            try:
                if bad:  # hand it back to the model to fix, like any tool error
                    result = {"error": f"not queued: {', '.join(bad)} did not come from a tool. Quote only "
                                       "figures a tool returned, or leave the numbers out, and call again."}
                else:
                    result = impl(args) if impl else {"error": f"tool '{name}' is not available"}
            except Exception as e:  # surface tool errors to the model, don't crash the turn
                result = {"error": str(e)}
            if dropped and isinstance(result, dict):
                result = {**result, "ignored_unstated_fields": dropped}
            dt = (time.perf_counter() - t0) * 1000
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
    return {"reply": plain_dashes(final.choices[0].message.content), "trace": trace, "steps": len(trace),
            "input_tokens": in_tok, "output_tokens": out_tok,
            "latency_ms": round(llm_ms), "cost_usd": cost_usd(in_tok, out_tok)}
