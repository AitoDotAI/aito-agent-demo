"""Write REPORT.md for the resolution scorecard from results/scorecard.json.

    python -m bench.report
"""

from __future__ import annotations

import json

from bench import config

# A clean, unthrottled gpt-5-mini call measured ~3.6s (single smoke call). Under
# the shared deployment's rate limit, 78 back-to-back calls measured a much higher
# p50 — that's a throttling artifact, so we headline the CONSERVATIVE clean figure
# and report the throttled p50 only as a caveat. We do NOT exploit the throttle.
LLM_CLEAN_MS = 3600


def main() -> None:
    s = json.loads((config.RESULTS_DIR / "scorecard.json").read_text())
    af, asamp, llm = s["aito_full"], s["aito_on_sample"], s["llm_on_sample"]
    aito_ms = af["latency_ms_p50"]
    throttled_ms = llm["latency_ms_p50"]
    speedup = LLM_CLEAN_MS / aito_ms

    intents = config.INTENTS
    def cell(d, i):
        v = d["per_intent"].get(i)
        return f"{v:.2f}" if v is not None else "—"
    per_intent_rows = "\n".join(f"| {i} | {cell(af, i)} | {cell(llm, i)} |" for i in intents)

    md = f"""# Resolution scorecard — predictive layer vs LLM agent

**Better · faster · cheaper**, across four resolution paths in one dataset. An LLM
agent resolves a ticket by reasoning and (in a real system) *chaining tool calls*; a
predictive layer turns "understand + resolve + fill the parameter" into a couple of
`_predict` calls answered from history — escalating only the unsure ones.

LLM agent: **{s['model']}** (Azure OpenAI), one structured call/ticket — a *generous* baseline
(a real tool-calling agent chains several round-trips). Aito scored on all {s['n_test']} test tickets;
the LLM agent measured on {s['n_llm_sample']}. LLM priced at ${s['price_in_per_mtok']}/{s['price_out_per_mtok']} per 1M in/out tokens.

## The scorecard
| axis | Aito (predict-first) | LLM agent ({s['model']}) |
|---|---|---|
| **better** — end-to-end accuracy | {af['end_to_end_acc']:.0%} (full {s['n_test']}) | {llm['end_to_end_acc']:.0%} (sample) |
| **faster** — latency / resolution | **{aito_ms:.0f} ms** | ~{LLM_CLEAN_MS/1000:.1f} s / call |
| **cheaper** — LLM $ / 1000 resolutions | **$0.00** | ${s['llm_cost_per_1000_usd']:.2f} ({s['llm_tokens_per_resolution']:.0f} tok/res) |
| **hands-off** — auto-resolved at gate {s['gate']} | **{s['aito_auto_resolve_rate']:.0%}** | n/a (no calibrated abstain) |

**Honest reading: accuracy is a tie ({af['end_to_end_acc']:.0%} vs {llm['end_to_end_acc']:.0%}).** This data is clean enough that
both resolve it perfectly, so *better* isn't the story here — the accuracy/calibration nuances are
in the tool-routing and assignment benchmarks. **Here the win is latency and cost:** ~{speedup:.0f}× faster
per single resolution, at zero per-ticket LLM cost.

## The real drama is multi-step workflows
The scorecard gives the agent its best case: **one** call. A real resolution is a *chain* —
classify → identify customer → look up the record → fill parameters → confirm — run
**sequentially** at ~{LLM_CLEAN_MS/1000:.1f}s each. Aito fires the equivalent `_predict`s in ~one round-trip.
The gap compounds with workflow length:

| workflow steps | LLM agent (sequential) | Aito |
|---|---|---|
| 1 | {LLM_CLEAN_MS/1000:.1f} s | ~{aito_ms/1000:.2f} s |
| 3 | {3*LLM_CLEAN_MS/1000:.1f} s | ~{aito_ms/1000:.2f} s |
| 6 | {6*LLM_CLEAN_MS/1000:.0f} s | ~{aito_ms/1000:.2f} s |

A six-step flow the agent runs in **~{6*LLM_CLEAN_MS/1000:.0f} seconds** is **effectively instant** with the
predictive layer — and free. For a customer waiting on a reply, that's the difference between a
20-second spinner and an immediate answer.

## Framing: Aito as a predictive cache in front of the LLM ("Redis for LLM")
The cleanest way to narrate this: Aito is a **smart cache** keyed on the ticket + its
structured context, with a *calibrated* confidence.
- **hit** (`$p ≥ gate`) → serve the predicted resolution instantly, ~free — this is the
  auto-resolve rate ({s['aito_auto_resolve_rate']:.0%} on this clean data; history- and traffic-dependent in general).
- **miss** (cold start / novel / low confidence) → fall through to the LLM, pay latency + tokens.
- **write-back** → the LLM's answer is logged and is in the *next* prediction (no retrain).
  The cache fills itself from its own misses, so the hit rate **warms up** with history.

A cold cache is 100% miss = plain LLM, **no worse than today** — so this is a Pareto add-on, and
"Aito needs history" simply means "the cache hasn't warmed yet." Blended economics behave like any
cache (effective cost ≈ miss-rate × LLM cost; effective latency ≈ hit-rate × {aito_ms:.0f}ms +
miss-rate × {LLM_CLEAN_MS/1000:.1f}s):

| cache hit rate | LLM $ / 1000 (= miss × ${s['llm_cost_per_resolution_usd']*1000:.2f}) | mean latency |
|---|---|---|
| 0% (cold) | ${s['llm_cost_per_resolution_usd']*1000:.2f} | {LLM_CLEAN_MS/1000:.1f} s |
| 40% | ${0.6*s['llm_cost_per_resolution_usd']*1000:.2f} | {(0.4*aito_ms+0.6*LLM_CLEAN_MS)/1000:.1f} s |
| 80% | ${0.2*s['llm_cost_per_resolution_usd']*1000:.2f} | {(0.8*aito_ms+0.2*LLM_CLEAN_MS)/1000:.1f} s |
| 95% | ${0.05*s['llm_cost_per_resolution_usd']*1000:.2f} | {(0.95*aito_ms+0.05*LLM_CLEAN_MS)/1000:.2f} s |

The honest hard problem is **cache invalidation**: if the right resolution changes (policy/reorg),
stale history can yield a confidently-wrong *hit*. Mitigations: the calibration gate, recency
weighting, TTL-style windows. That — not cold start — is the risk to manage.

## Per-path accuracy (intent + its parameter)
| path | Aito | LLM agent |
|---|---|---|
{per_intent_rows}

(`cancel_service`/`refund` → **service**; `check_outage`/`find_shop` → **location**;
`repair_help` → **KB article**; `check_balance` → no parameter.)

## Honest caveats
- **Accuracy is a tie on this clean data** — the win demonstrated here is latency & cost, not
  correctness. On messy or novel tickets the accuracy/calibration differences (and Aito's need for
  history) from the other benchmarks apply.
- **Latency caveat:** a clean gpt-5-mini call is ~{LLM_CLEAN_MS/1000:.1f}s; under the shared deployment's rate
  limit, 78 back-to-back calls measured a p50 of ~{throttled_ms/1000:.0f}s. We headline the conservative ~{LLM_CLEAN_MS/1000:.1f}s
  and do **not** exploit the throttle. Aito's {aito_ms:.0f}ms is the measured round-trip for two `_predict`s.
- **Cost is modest per ticket for a mini model** (${s['llm_cost_per_1000_usd']:.2f}/1000); it grows with workflow
  length, model size (Opus-class is ~40× the token price), and volume — while Aito stays $0 LLM.
- The LLM baseline is a **single structured call** (best case). A real tool-calling agent chains
  round-trips, so its true latency/cost are higher — the gap shown is a lower bound.
- Synthetic, seeded data; phrasing uses aliases, not canonical tokens. The transferable result is the
  **shape**: comparable accuracy, order-of-magnitude less latency and cost, with a calibrated
  auto-resolve slice that needs no LLM at all.
"""
    (config.RESULTS_DIR / "REPORT.md").write_text(md)
    print("wrote REPORT.md")


if __name__ == "__main__":
    main()
