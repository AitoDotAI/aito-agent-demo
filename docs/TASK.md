# TASK.md — Telco Agent Tool-Routing Benchmark

## Objective

Build a reproducible benchmark that measures, on a telco support-ticket task, whether a predictive tool layer (Aito `_predict`) beats LLM-only agents on cost, latency, and calibrated reliability **without losing resolution quality**. The output replaces the modeled numbers in the agent demo (`aito-agent-demo-shell.html`) with measured ones, via a `results.json` it can read.

The single claim under test, stated so it can fail:

> As the backend tool space grows, an LLM agent's tool selection degrades in accuracy, cost, and latency, while an Aito-predicted tool layer holds — and crucially, Aito's confidence is calibrated well enough to auto-fire the easy steps and escalate the hard ones, instead of guessing.

If the numbers do not show this, report that plainly. A clean negative result is a success for this task.

---

## Non-negotiable principles (read first)

These reflect how this codebase is run. Violating any of them fails the task.

1. **Never silently filter or discard unexpected data.** If a ticket, tool, or API response is malformed or missing a field, `assert` and surface it. Do not drop rows to make a run "pass."
2. **Do not fake metrics.** A benchmark that improves a number by doing less work is a bug. Resolution-quality metrics are computed against held-out labels, not against the agent's own output. Latency and token counts are measured, not estimated, for the real LLM and Aito calls.
3. **Do not invent inference logic.** Aito does the prediction. The Aito agent's job is to call the `_predict` API and read `$p`. Do not implement your own ranking, scoring, or calibration heuristic. If a result looks wrong, the fix is the query or the data, never a hand-rolled scorer.
4. **Beat the competent baseline, not a strawman.** The primary comparison is against retrieval-shortlisted tool selection (Baseline B below), not against dumping all tools in context. If Aito only beats the naive baseline, say so.
5. **No tuning on the test set.** The gate threshold and any retrieval-k are chosen on a validation split. The test split is touched once, for the final numbers.
6. **Deterministic.** Fixed seeds everywhere. Same inputs produce same splits and same dataset. Log every LLM and Aito call (request, response, latency) to `results/calls.jsonl`.
7. **Report weaknesses.** The REPORT.md must include where Aito does not win (it will not win at small tool counts) and the escalation mis-route rate. Honesty is the point; the target audience will check.

---

## Project structure to build

```
telco-tool-routing-bench/
  README.md
  requirements.txt
  .env.example              # ANTHROPIC_API_KEY, AITO_URL, AITO_API_KEY, AITO_RW_KEY
  data/
    tools.py                # scalable tool catalog (N in {12,40,120,340})
    tickets.py              # labeled ticket set (synthetic, seeded)
    generate.py             # builds train/val/test splits -> data/*.json
  aito/
    schema.py               # Aito table schema for `tickets`
    upload.py               # creates table + batch-uploads TRAIN split to Aito
    predict.py              # thin wrapper over Aito _predict (tool + escalation_target)
  bench/
    config.py               # tool-count sweep, gate threshold, k, model name, seeds
    llm_agent.py            # Baseline A (all tools) + Baseline B (retrieval shortlist)
    aito_agent.py           # Aito-gated agent: predict -> gate -> auto/assist/escalate
    metrics.py              # accuracy, cost, latency, calibration (ECE + reliability)
    runner.py               # runs 3 configs across the sweep on the TEST split
    report.py               # writes results.json, REPORT.md, calibration.png, sweep.png
  results/
    results.json            # consumed by the demo UI
    REPORT.md
    calls.jsonl
    calibration.png
    sweep.png
```

CC is good at the data, the API wrappers, the runner, and the report. Build those. The only "intelligence" is Aito's API.

---

## Dataset spec

Synthetic but realistic. Telco MVNO support.

**Tool catalog (`data/tools.py`).** A function `build_tools(n)` returns `n` tools, each `{name, signature, description, domain}`. Start from a hand-written core of ~25 real-feeling tools (order_sms_pack, run_line_diagnostic, reset_modem, check_invoice, issue_refund, create_order, check_stock, activate_sim, update_plan, check_roaming, check_coverage, port_number, schedule_technician, close_account, etc.). Pad to `n` with plausible distractor tools across domains (billing, network, provisioning, sales, retention, devices). Distractors must be realistic, not obvious filler — they are what makes selection hard.

**Tickets (`data/tickets.py`).** At least 300 labeled tickets. Each: `{id, text, correct_tool, difficulty in {clear,medium,ambiguous}, escalation_target_or_null, is_escalation}`. For `clear` and `medium`, there is one correct tool. For `ambiguous`, the right behavior is **escalate** to a named desk (Network Ops, Billing, Retention, Tech Support, Sales), and `correct_tool` may be null. Vary phrasing heavily so it is not keyword-trivial. Seed it.

**Splits (`data/generate.py`).** Stratify by difficulty. TRAIN (~60%) populates Aito's history. VAL (~15%) sets the gate threshold and retrieval-k. TEST (~25%) is the held-out evaluation set, touched once. Write `data/{train,val,test}.json`. Assert no ticket id appears in two splits.

---

## The three configurations

All three resolve the **same TEST tickets**, with the **same Anthropic model** (set in `config.py`) for every LLM step.

**Baseline A — LLM, full tool space.** All `n` tool signatures + descriptions in the prompt. One LLM call selects the tool (Anthropic tool-use or a structured-output selection). On ambiguity it still picks a tool (LLM-only baselines do not have a calibrated abstain signal; this is the point).

**Baseline B — LLM, retrieval-shortlisted (the competent baseline).** Embed tool descriptions once (a sentence-transformer locally, or an embeddings API — keep it a real, standard retrieval setup). For each ticket, embed the text, take top-k tools by cosine, put only those k in the prompt, LLM selects. k chosen on VAL. This is what a good engineer would actually build, so it is the bar to clear.

**Aito — predicted + gated.** For each ticket:
- Call `_predict` for `tool` over the `tickets` table (TRAIN data is in Aito). Read top candidate and `$p`.
- If `$p >= gate` (gate set on VAL): **auto-fire**, no LLM call.
- Else if `$p >= assist_floor`: pass the top-4 Aito candidates to the LLM, which picks (small context, cheap).
- Else: **escalate**. Predict `escalation_target` with a second `_predict`; the routed desk is whatever Aito returns. A wrong desk is a mis-route and counts against quality.

---

## Aito integration (pinned — do not improvise)

**Schema (`aito/schema.py`).** Table `tickets`:
```json
{
  "columns": {
    "ticket_id": {"type": "String"},
    "text": {"type": "Text", "analyzer": "english"},
    "tool": {"type": "String"},
    "escalation_target": {"type": "String", "nullable": true}
  }
}
```

**Upload (`aito/upload.py`).** Create the table, batch-upload the TRAIN split only. Never upload VAL or TEST. Assert the row count after upload equals the TRAIN size.

**Predict tool (`aito/predict.py`).**
```json
POST {AITO_URL}/api/v1/_predict
{
  "from": "tickets",
  "where": { "text": "<ticket text>" },
  "predict": "tool",
  "select": ["$p", "feature", "$why"],
  "limit": 4
}
```
Top hit's `$p` is the confidence used by the gate. Do not transform or recalibrate it.

**Predict escalation target** (only on escalate path): same shape, `"predict": "escalation_target"`.

If the API returns an unexpected shape, assert. Do not coerce.

---

## Metrics (pinned definitions)

Per `(config, tool_count)`:

- **tool_accuracy**: of non-escalated decisions, fraction where chosen tool == correct_tool.
- **handled_correct / total**: a ticket is handled correctly if (resolved with correct tool) OR (correctly escalated to the right desk on an `ambiguous` ticket). A wrong tool, or a mis-routed escalation, is not correct. This is the headline quality number and it is computed against TEST labels.
- **llm_calls**: count of real Anthropic calls.
- **tokens**: measured input+output tokens, summed (from API usage).
- **cost_usd**: tokens priced at the model's published rate in `config.py`.
- **latency_ms_total** and **latency_ms_p50**: measured wall-clock around each call.
- **auto_fire_rate** (Aito only): fraction of tickets resolved with zero LLM calls.
- **escalations**, **escalations_misrouted** (Aito only).

**Calibration (the load-bearing metric, Aito only).** On TEST, bucket Aito's top-1 `$p` into 10 bins. For each bin record mean predicted confidence and empirical accuracy. Compute **ECE** (expected calibration error) = sum over bins of (n_bin/N) * |acc_bin - conf_bin|. Produce `calibration.png` (reliability diagram: predicted vs actual, with the diagonal). The auto-fire gate is justified only if high-confidence bins are empirically accurate. State the ECE in REPORT.md. If calibration is poor, the whole auto-fire claim fails, and the report must say so.

**Sweep.** Run the full thing for tool_count in {12, 40, 120, 340}. Aito's TRAIN data and queries are identical across sweeps (the tool space changes for the LLM baselines, not for Aito). `sweep.png` plots cost, latency, and tool_accuracy vs tool_count for all three configs. The expected story is divergence; if it does not diverge, report that.

---

## results.json schema (consumed by the demo UI)

```json
{
  "generated_at": "ISO-8601",
  "model": "claude-...-",
  "n_test": 0,
  "configs": ["baseline_full", "baseline_retrieval", "aito"],
  "by_tool_count": {
    "40": {
      "baseline_full":      {"tool_accuracy":0,"handled_correct":0,"total":0,"llm_calls":0,"tokens":0,"cost_usd":0,"latency_ms_total":0,"latency_ms_p50":0},
      "baseline_retrieval": {"...": 0},
      "aito": {"tool_accuracy":0,"handled_correct":0,"total":0,"llm_calls":0,"tokens":0,"cost_usd":0,"latency_ms_total":0,"latency_ms_p50":0,
               "auto_fire_rate":0,"escalations":0,"escalations_misrouted":0,
               "calibration":{"ece":0,"bins":[{"conf":0,"acc":0,"n":0}]}}
    }
  }
}
```

The demo HTML currently hardcodes modeled values in its `simulate()` function. Final step: document in REPORT.md exactly which `results.json` fields map to which demo KPI cards (auto_fire_rate, handled_correct/total, llm_calls, escalations/escalations_misrouted) so the modeled numbers can be swapped for measured ones.

---

## Acceptance criteria

The task is done only when all pass:

1. `python -m data.generate` writes train/val/test with no id overlap (asserted).
2. `python -m aito.upload` loads TRAIN into Aito and asserts the row count.
3. `python -m bench.runner` runs all 3 configs across the full sweep on TEST, logging every call to `calls.jsonl`.
4. `results.json` validates against the schema above and contains real measured tokens and latency (not zeros, not constants).
5. `calibration.png`, `sweep.png`, and `REPORT.md` are produced.
6. REPORT.md states: the headline cost/latency deltas at 120 tools, the ECE, the auto-fire rate, the mis-route rate, **and at least one axis or tool-count where Aito does not win.**
7. Re-running with the same seeds reproduces the splits and dataset exactly.

---

## Run

```
cp .env.example .env        # fill ANTHROPIC_API_KEY, AITO_URL, AITO_API_KEY, AITO_RW_KEY
pip install -r requirements.txt
python -m data.generate
python -m aito.upload
python -m bench.runner
python -m bench.report
```

## Do not

- Do not stack optimizations on parts that are not yet implemented and passing.
- Do not declare a step complete before its acceptance criterion passes.
- Do not adjust the gate, k, or any threshold using TEST data.
- Do not hand-roll the prediction or a calibration correction.
- Do not drop or coerce malformed data; assert and stop.

## Ask before assuming

If the Aito instance is not reachable, the model name/pricing is unset, or `_predict` returns a shape these queries do not expect, stop and ask rather than stubbing it out. A stub that returns plausible numbers is worse than a failing run, because it hides the truth this benchmark exists to find.
