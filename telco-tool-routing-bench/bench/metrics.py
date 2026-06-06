"""Metric definitions (pinned by TASK.md). All quality metrics are computed
against the held-out TEST labels, never against an agent's own output.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from bench import config
from bench.decision import Decision


def _handled_correct(d: Decision, gold: dict) -> bool:
    """A ticket is handled correctly iff resolved with the correct tool, OR
    correctly escalated to the right desk on a genuinely ambiguous ticket."""
    if d.escalated:
        return bool(gold["is_escalation"]) and d.routed_desk == gold["escalation_target"]
    return (not gold["is_escalation"]) and d.chosen_tool == gold["correct_tool"]


def _all_call_latencies(decisions: list[Decision]) -> list[float]:
    out: list[float] = []
    for d in decisions:
        for rec in d.call_records:
            if "latency_ms" in rec:
                out.append(float(rec["latency_ms"]))
    return out


def calibration(decisions: list[Decision], gold_by_id: dict[str, dict], n_bins: int = 10) -> dict:
    """Reliability of Aito's raw top-1 tool confidence on TEST.

    For each ticket: predicted confidence = aito_top_p; the prediction is
    'accurate' iff the top predicted tool equals the gold correct_tool. Ambiguous
    tickets (correct_tool=None) are therefore counted as inaccurate — which is the
    point: low confidence there should correctly signal 'do not auto-fire'.
    ECE = sum_bins (n_bin/N) * |acc_bin - conf_bin|.
    """
    pts = [(d.aito_top_p, d.aito_tool_pred == gold_by_id[d.ticket_id]["correct_tool"])
           for d in decisions if d.aito_top_p is not None]
    n = len(pts)
    assert n > 0, "calibration called with no aito predictions"
    bins = []
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        # last bin is inclusive of 1.0
        in_bin = [(p, ok) for p, ok in pts if (lo <= p < hi or (b == n_bins - 1 and p == 1.0))]
        if not in_bin:
            bins.append({"conf": round((lo + hi) / 2, 3), "acc": None, "n": 0})
            continue
        conf = sum(p for p, _ in in_bin) / len(in_bin)
        acc = sum(1 for _, ok in in_bin if ok) / len(in_bin)
        bins.append({"conf": round(conf, 4), "acc": round(acc, 4), "n": len(in_bin)})
        ece += len(in_bin) / n * abs(acc - conf)
    return {"ece": round(ece, 4), "bins": bins, "n": n}


def compute(decisions: list[Decision], gold_by_id: dict[str, dict]) -> dict:
    """Aggregate metrics for one (config, tool_count) cell."""
    assert decisions, "no decisions"
    total = len(decisions)
    is_aito = decisions[0].config_name == "aito"

    handled = sum(1 for d in decisions if _handled_correct(d, gold_by_id[d.ticket_id]))

    non_esc = [d for d in decisions if not d.escalated]
    tool_hits = sum(
        1 for d in non_esc
        if d.chosen_tool == gold_by_id[d.ticket_id]["correct_tool"]
    )
    tool_accuracy = tool_hits / len(non_esc) if non_esc else 0.0

    llm_calls = sum(d.llm_calls for d in decisions)
    in_tok = sum(d.input_tokens for d in decisions)
    out_tok = sum(d.output_tokens for d in decisions)
    lat = _all_call_latencies(decisions)
    lat_total = sum(lat)
    lat_p50 = statistics.median(lat) if lat else 0.0

    out = {
        "tool_accuracy": round(tool_accuracy, 4),
        "handled_correct": handled,
        "total": total,
        "llm_calls": llm_calls,
        "tokens": in_tok + out_tok,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(config.cost_usd(in_tok, out_tok), 6),
        "latency_ms_total": round(lat_total, 1),
        "latency_ms_p50": round(lat_p50, 1),
    }

    if is_aito:
        autos = sum(1 for d in decisions if d.mode == "auto")
        escs = [d for d in decisions if d.escalated]
        misrouted = sum(
            1 for d in escs
            if not (gold_by_id[d.ticket_id]["is_escalation"]
                    and d.routed_desk == gold_by_id[d.ticket_id]["escalation_target"])
        )
        out.update({
            "auto_fire_rate": round(autos / total, 4),
            "escalations": len(escs),
            "escalations_misrouted": misrouted,
            "calibration": calibration(decisions, gold_by_id),
        })
    else:
        # honest diagnostic: how often the baseline named a tool not in its catalog
        out["invalid_tool_selections"] = sum(1 for d in decisions if not d.valid_tool)

    return out


@dataclass
class ValScore:
    """Used to pick gate/assist_floor/k on VAL."""
    handled_correct: int
    total: int
    auto_fire_rate: float
    confident_accuracy: float    # accuracy on auto-fired (gated) decisions
