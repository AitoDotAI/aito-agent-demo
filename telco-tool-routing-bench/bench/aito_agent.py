"""Aito-gated agent: predict -> gate -> auto / assist / escalate.

For each ticket:
  1. _predict the `tool`. Read the top candidate and its raw `$p`.
     (We record top_p + top_feature for EVERY ticket so calibration can bin the
      raw confidence, regardless of which branch we take.)
  2. $p >= gate            -> AUTO-FIRE the top tool. No LLM call.
  3. assist_floor <= $p    -> ASSIST: hand the top-4 Aito candidates to the LLM,
                               which picks one (small, cheap prompt).
  4. else                  -> ESCALATE: _predict the `escalation_target`; route
                               to whatever desk Aito returns (which can be wrong).

No hand-rolled scoring or recalibration: the gate compares Aito's raw `$p`
against thresholds chosen on VAL. The "intelligence" is entirely Aito's.
"""

from __future__ import annotations

from aito.predict import AitoPredictor
from bench import config
from bench.decision import Decision
from bench.llm import LLMClient
from data.tools import ANSWER_TOOLS

# name -> tool dict, for giving the assist LLM real descriptions of Aito's
# top candidates (Aito only ever predicts trained tool labels = answer tools).
_TOOL_BY_NAME = {t["name"]: t for t in ANSWER_TOOLS}


def resolve_aito(
    predictor: AitoPredictor,
    llm: LLMClient,
    ticket: dict,
    gate: float,
    assist_floor: float,
) -> Decision:
    tool_pred = predictor.predict_tool(ticket["text"])
    top = tool_pred.top
    records: list[dict] = [{
        "config": "aito", "tool_count": None, "ticket_id": ticket["id"],
        "op": "aito.predict_tool", "top_feature": top.feature, "top_p": round(top.p, 5),
        "candidates": [(c.feature, round(c.p, 5)) for c in tool_pred.candidates],
        "latency_ms": round(tool_pred.latency_ms, 1),
    }]
    latency = tool_pred.latency_ms
    in_tok = out_tok = 0
    llm_calls = 0

    if top.p >= gate:
        mode, chosen, escalated, routed = "auto", top.feature, False, None

    elif top.p >= assist_floor:
        mode, escalated, routed = "assist", False, None
        cand_names = [c.feature for c in tool_pred.candidates if c.feature]
        shortlist = [_TOOL_BY_NAME[n] for n in cand_names if n in _TOOL_BY_NAME]
        sel = llm.select_tool(ticket["text"], shortlist)
        chosen = sel.tool
        llm_calls, in_tok, out_tok = 1, sel.input_tokens, sel.output_tokens
        latency += sel.latency_ms
        records.append({
            "config": "aito", "tool_count": None, "ticket_id": ticket["id"],
            "op": "llm.select_tool(assist)", "n_tools_in_prompt": len(shortlist),
            "input_tokens": sel.input_tokens, "output_tokens": sel.output_tokens,
            "latency_ms": round(sel.latency_ms, 1), "chosen_tool": sel.tool,
        })

    else:
        mode, chosen, escalated = "escalate", None, True
        esc_pred = predictor.predict_escalation(ticket["text"])
        routed = esc_pred.top.feature
        latency += esc_pred.latency_ms
        records.append({
            "config": "aito", "tool_count": None, "ticket_id": ticket["id"],
            "op": "aito.predict_escalation", "top_feature": esc_pred.top.feature,
            "top_p": round(esc_pred.top.p, 5), "latency_ms": round(esc_pred.latency_ms, 1),
        })

    return Decision(
        config_name="aito", tool_count=0, ticket_id=ticket["id"],
        chosen_tool=chosen, escalated=escalated, routed_desk=routed, mode=mode,
        llm_calls=llm_calls, input_tokens=in_tok, output_tokens=out_tok,
        latency_ms=latency, aito_top_p=top.p, aito_tool_pred=top.feature,
        call_records=records,
    )
