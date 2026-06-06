# Telco Agent Tool-Routing Benchmark

Measures whether a **predictive tool layer (Aito `_predict`)** beats LLM-only
agents on cost, latency and calibrated reliability on a telco support-ticket
tool-routing task — **without losing resolution quality**. Output feeds measured
numbers into `../docs/aito-agent-demo-shell.html` via `results/results.json`.

The single claim under test (stated so it can fail):

> As the backend tool space grows, an LLM agent's tool selection degrades in
> accuracy, cost and latency, while an Aito-predicted tool layer holds — and
> Aito's confidence is calibrated well enough to auto-fire the easy steps and
> escalate the hard ones, instead of guessing.

A clean negative result is a success. See `results/REPORT.md` after a run; it is
required to state where Aito does **not** win and the mis-route rate, and it
flags that the flat Aito sweep line is **structural** (Aito never sees the
distractor tools), not an emergent property.

## Layout
```
data/    tools.py (scalable catalog), tickets.py (300 seeded labels), generate.py (splits)
aito/    schema.py, upload.py (TRAIN only), predict.py (_predict wrapper)
bench/   config.py, llm.py (Azure OpenAI gpt-5-mini), llm_agent.py (Baselines A/B),
         aito_agent.py (predict→gate→auto/assist/escalate), select.py (VAL thresholds),
         metrics.py (accuracy, cost, latency, ECE), runner.py, report.py
results/ results.json, REPORT.md, calls.jsonl, calibration.png, sweep.png
```

## Run
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# credentials live in the repo-root ../.env (shared with the parent demo):
#   AITO_API_URL, AITO_API_KEY, AITO_RW_KEY,
#   OPENAI_MODEL_URL, OPENAI_MODEL_DEPLOYMENT, OPENAI_MODEL_API_VERSION, OPENAI_MODEL_API_KEY

python -m data.generate      # write train/val/test (reproducible, no id overlap)
python -m aito.upload        # create table + upload TRAIN only (asserts row count)
python -m bench.runner       # VAL threshold pick + all 3 configs on TEST (logs calls.jsonl)
python -m bench.report       # results.json, REPORT.md, calibration.png, sweep.png
```
Smoke a cheap subset first: `python -m bench.runner --limit 8`.

## Design notes that matter
- **≤10 distinct answer tools.** The smallest sweep catalog is 12, and the same
  tickets are scored at every N, so every `correct_tool` must exist at every N.
  Growing N only adds realistic **distractors** the LLM baselines must wade
  through and Aito never sees. (See `data/tools.py`.)
- **`tool` is nullable in the Aito schema** (deviation from TASK.md's pinned
  schema, documented in `aito/schema.py`): ambiguous tickets carry a null tool
  so `_predict` returns low, spread `$p` → the gate escalates. A sentinel
  "escalate" class would fake calibrated abstention.
- **No tuning on TEST.** gate, assist_floor and retrieval-k are chosen on VAL
  (`bench/select.py` → `results/chosen_params.json`); TEST is scored once.
- **Aito runs once.** Its queries are identical across the sweep, so the runner
  runs it once and the report replicates the cell — avoiding re-billing assist
  calls 4×.
- **Nothing is faked.** Tokens and latency are measured from the live APIs;
  malformed responses assert rather than coerce.
