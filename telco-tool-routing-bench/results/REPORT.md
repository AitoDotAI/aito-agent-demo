# Telco tool-routing benchmark — results

_Generated 2026-06-04T19:37:08.636617+00:00_
_Model for every LLM step: **gpt-5-mini** (Azure OpenAI). n_test = 75._

## Verdict — the claim holds on efficiency, FAILS on quality
A mixed, honest result (a clean partial-negative, which the task treats as success):

- **Cost & latency: Aito wins decisively, and the gap widens with the tool count.** At 340 tools Aito cost **74× less** than Baseline A and **9× less** than Baseline B, on **14 LLM calls vs 75**. Aito's cost/latency/tokens are flat across the sweep; the baselines climb.
- **Resolution quality: Aito does NOT beat a strong LLM.** Aito handled **43/75** correctly — *below Baseline A at every tool count* (52/75 at 120) and below Baseline B at small N. The flat 43/75 only overtakes the *retrieval* baseline once that baseline degrades past it (≥120 tools).
- **Calibration is moderate, not clean: ECE = 0.1113.** The auto-fire gate fires the top confidence bin, which is ~88% accurate — useful, but the model is overconfident, which is why the auto-fire claim is real but not airtight.

So: a predictive tool layer is the right call when **cost, latency and throughput** dominate and ~39% hands-free automation at 86% per-decision accuracy is worth trading a few points of end-to-end resolution for. It is the wrong call if **maximising handled-correct** is the only goal and you can afford a strong LLM on every step.

## What was measured
Three configs resolve the **same 75 held-out TEST tickets**:
- **Baseline A** — all N tool descriptions in the prompt, one LLM call selects.
- **Baseline B** — retrieval-shortlisted top-8 tools (local MiniLM cosine), then one LLM call. *The competent baseline.*
- **Aito** — `_predict` the tool, gate on raw `$p` (gate=0.92, assist_floor=0.86): auto-fire / assist-from-4 / escalate.

Thresholds and k were chosen on VAL only; TEST was scored once.

## Headline (at 120 tools)
| metric | Baseline A | Baseline B | Aito |
|---|---|---|---|
| handled correctly | 52/75 | 48/75 | 43/75 |
| tool accuracy (non-escalated) | 0.6933 | 0.64 | 0.8605 |
| LLM calls | 75 | 75 | 14 |
| tokens | 156,105 | 24,108 | 3,433 |
| cost (USD) | 0.045773 | 0.012332 | 0.001473 |
| total latency (ms) | 121,934.3 | 124,512.1 | 30,825.5 |

**vs the competent baseline (B) at 120 tools:** Aito used **88% less cost** and **75% less total latency**, auto-firing 39% of tickets with zero LLM calls.

## Calibration (the load-bearing metric)
- **ECE = 0.1113** over 75 TEST tickets, 10 bins (see `calibration.png`).
- Auto-fire rate: **39%**.
- The auto-fire gate is justified only if high-confidence bins are empirically accurate; the reliability diagram shows whether they are. If the high bins sit below the diagonal, the auto-fire claim is weakened and should not be trusted.

## Escalation quality
- Escalations: **32**, of which **26 were not a correct desk routing** (mis-routed or unnecessary). Mis-route rate = 81%.
- This is a real cost: a mis-routed escalation is counted as NOT handled correctly.

## Why Aito's quality trails despite higher per-decision accuracy
Decomposing Aito's 75 decisions explains the gap:
- **29 auto-fired**, **14 assisted** (LLM picks from 4), **32 escalated**.
- When Aito *acted* (fired or assisted) it was right **37/43** (86%) — **higher per-decision accuracy than either baseline**. The problem is not the tool predictions it makes.
- The quality is lost on the **escalate** path: of 32 escalations, **23 were unnecessary** (clear/medium tickets Aito should have resolved but abstained on — calibrated abstention set too aggressively), and of the **15 genuinely ambiguous** tickets only **6 reached the right desk** (3 of the ambiguous escalations mis-routed).
- Root causes: (1) the VAL gate never reached the 0.95 auto-fire-accuracy target (peaked ~0.91), so the gate/floor landed conservatively and over-escalate; (2) the `escalation_target` predictor is trained on only ~7 examples per desk (sparse), so desk routing is weak. Both are honest limitations of this dataset size, not bugs.

## Where Aito does NOT win
- At 12 tools, Baseline A (full) handled 58/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.
- At 12 tools, Baseline B (retrieval) handled 58/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.
- At 40 tools, Baseline A (full) handled 55/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.
- At 40 tools, Baseline B (retrieval) handled 52/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.
- At 120 tools, Baseline A (full) handled 52/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.
- At 120 tools, Baseline B (retrieval) handled 48/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.
- At 340 tools, Baseline A (full) handled 52/75 ≥ Aito's 43/75 — Aito does not win on resolution quality here.

At small tool counts the LLM baselines have an easy job (few confusable tools), so the predictive layer's cost/latency advantage is small or absent and its escalations can cost it quality. The benchmark is designed to show this.

## IMPORTANT caveat — the flat Aito line is structural, not empirical
Aito's TRAIN data and `_predict` queries are **identical at every tool count** — Aito never sees the distractor tools that grow the catalog (only the LLM baselines do). So "Aito holds flat as N grows" is true **by construction**, not an emergent property of the model. The genuinely falsifiable results here are the **absolute accuracy**, the **ECE**, and the **mis-route rate** — not the slope of the sweep. The sweep shows the *LLM baselines degrading*; Aito's invariance is the experimental setup, and `sweep.png` should be read that way.

Secondary caveat: tickets and tools are **synthetic and seeded**, and Aito's TRAIN is drawn from the same generator as TEST, so calibration on this data is easier than it would be on real telco traffic. Treat the ECE as a best case.

Model note: TASK.md specifies an Anthropic model; this run substitutes **gpt-5-mini** (Azure OpenAI) for every LLM step. Both baselines use the identical model, so the comparison is not confounded.

## results.json → demo KPI-card mapping
The demo (`docs/aito-agent-demo-shell.html`) currently hardcodes modeled values in `simulate()`. Measured replacements, per tool count `by_tool_count["<n>"]`:

| demo KPI card | results.json field |
|---|---|
| "Auto-fired · no LLM" | `aito.auto_fire_rate` |
| "Handled correctly" `X/10` | `aito.handled_correct` / `aito.total` |
| "LLM calls" (Aito) | `aito.llm_calls` |
| "Escalations" | `aito.escalations` (mis-routed: `aito.escalations_misrouted`) |
| baseline "LLM calls" comparison | `baseline_retrieval.llm_calls` (or `baseline_full.llm_calls`) |
| baseline "handled" comparison | `baseline_retrieval.handled_correct` / `.total` |
| token/latency cut in the verdict line | derived from `*.tokens` and `*.latency_ms_total` |

Note: the demo animates a 10-ticket narrative while these numbers are aggregates over 75 TEST tickets — surface a curated 10-ticket showcase for the animation and the aggregates for the KPI cards; they are not the same number.
