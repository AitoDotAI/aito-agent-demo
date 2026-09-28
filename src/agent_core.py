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
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}


def plain_dashes(text: str) -> str:
    """User-facing copy uses no em-dashes; the model still writes some despite the
    prompt. A spaced one reads as a comma, an unspaced one as a hyphen."""
    return re.sub(r"\s*—\s*", ", ", re.sub(r"(?<=\w)—(?=\w)", "-", text or ""))


# A percentage ("~70%") or a multiplier written onto its number ("3.7x", "3.7×"); "2 x 30 min"
# is a count, not a claim.
_FIGURE = re.compile(r"(\d+(?:\.\d+)?)(\s*%|[x×](?!\w))", re.I)


def _sources(trace: list[dict]) -> list:
    """What the tools actually returned this turn. A guard's own rejection or
    annotation is not a source: otherwise "70% did not come from a tool" would
    ground 70% on the retry, and a dropped guess would ground itself."""
    out = []
    for t in trace:
        r = t.get("result")
        if isinstance(r, dict):
            if "error" in r:
                continue
            r = {k: v for k, v in r.items() if k != "ignored_unstated_fields"}
        out.append(r)
    return out


def _numbers(values: Any, out: set[float]) -> set[float]:
    if isinstance(values, dict):
        for v in values.values():
            _numbers(v, out)
    elif isinstance(values, list):
        for v in values:
            _numbers(v, out)
    elif isinstance(values, (int, float)) and not isinstance(values, bool):
        out.add(float(values))
    elif isinstance(values, str):
        out |= {float(x) for x in re.findall(r"\d+(?:\.\d+)?", values)}
    return out


def ungrounded_figures(draft: dict, trace: list[dict], history: list[dict]) -> list[str]:
    """Percentages / multipliers in a draft that no tool returned this turn and no
    earlier message stated. Earlier turns' tool results only survive as the
    assistant's own quoted text, so that text counts as a source too. A figure
    matches when it is a source number rounded: 59% for 0.587 or 58.7, 3.7x for
    3.66, but not 3.3x for 3.7."""
    raw: set[float] = set()
    _numbers(_sources(trace), raw)
    _numbers([m.get("content") or "" for m in history], raw)
    pct = raw | {x * 100 for x in raw if 0 <= x <= 1}
    text = " ".join(v for v in draft.values() if isinstance(v, str))
    bad = []
    for m in _FIGURE.finditer(text):
        f, is_pct = float(m.group(1)), "%" in m.group(2)
        ok = any(abs(f - k) <= 0.5 for k in pct) if is_pct else any(abs(f - k) <= 0.05 for k in raw if k >= 1)
        if not ok:
            bad.append(m.group(0))
    return bad


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _heard(text: str) -> set[str]:
    """Words the user said. One- and two-letter tokens only count as a standalone
    capital ("an L deal", "XL"), so "I'm" or "it's" never says size M or S."""
    words = {w for w in _norm(text).split() if len(w) > 2}
    return words | {w.lower() for w in re.findall(r"(?<![\w'’])[A-Z]{1,2}(?![\w'’])", text or "")}


def _word_said(w: str, heard: set[str]) -> bool:
    """Exactly, or as an inflection of a 5+ letter word: "logistic" says
    "Logistics", but "part" never says "Partner" nor "eventually" "Event"."""
    if w in heard:
        return True
    for h in heard:
        short, long_ = sorted((w, h), key=len)
        if len(short) >= 5 and long_.startswith(short) and len(long_) - len(short) <= 3:
            return True
    return False


def _said(value: str, heard: set[str], text: str, aliases: dict[str, list[str]]) -> bool:
    if any(f" {_norm(a)} " in f" {text} " for a in aliases.get(value, [])):
        return True
    words = [w for w in _norm(value).split()]
    return bool(words) and all(_word_said(w, heard) for w in words)


def _returned(values: Any, key: str = "", out: dict | None = None) -> dict[str, set[str]]:
    """Field -> the string values tools returned for it: {"personalization": "High"}
    and driver pairs {"field": "complexity", "value": "High"} alike."""
    out = {} if out is None else out
    if isinstance(values, dict):
        if isinstance(values.get("field"), str) and isinstance(values.get("value"), str):
            out.setdefault(values["field"], set()).add(values["value"])
        for k, v in values.items():
            _returned(v, k, out)
    elif isinstance(values, list):
        for v in values:
            _returned(v, key, out)
    elif isinstance(values, str) and key:
        out.setdefault(key, set()).add(values)
    return out


def unstated_args(args: dict, spec: dict, trace: list[dict], history: list[dict]) -> dict:
    """The enum arguments whose value the user never said and no tool returned
    for that field: the model filled them in. A value a tool returned grounds only
    its own field ("personalization": "High" says nothing about complexity).
    Free-text arguments are not checked. A tool spec's `aliases`
    ({value: [phrase, ...]}) lists other ways a user says a value."""
    said = " ".join(m.get("content") or "" for m in history if m.get("role") == "user")
    heard, text = _heard(said), _norm(said)
    returned = _returned(_sources(trace))
    props = spec.get("parameters", {}).get("properties", {})
    aliases = spec.get("aliases", {})

    def from_tool(k: str, v: str) -> bool:
        return any(v in vals for f, vals in returned.items() if f == k or f.endswith("_" + k))

    return {k: v for k, v in args.items()
            if isinstance(v, str) and "enum" in props.get(k, {})
            and not (_said(v, heard, text, aliases) or from_tool(k, v))}


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
    msgs += [{"role": m["role"], "content": m.get("content") or ""} for m in history]

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
