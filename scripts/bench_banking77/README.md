# Aito vs LLMs on banking77

A reproducible benchmark: how accurate, fast and token-hungry an intent decision
is with Aito alone, with an LLM alone, with an LLM plus retrieval (RAG), and with
Aito and an LLM together. Every number on the benchmark page comes from
`results/banking77.json`, which `summarize.py` writes from the per-query run
files in `results/runs/`.

## The data

[banking77](https://github.com/PolyAI-LDN/task-specific-datasets) (PolyAI,
CC BY 4.0): 13,083 customer messages to a bank, each labelled with one of 77
intents. The standard split is used: 10,003 training messages, 3,080 test
messages. `fetch.py` downloads both files and checks them against pinned
sha256 hashes.

- Only the **training** split is loaded into Aito. The test split never is, so
  every scored prediction is on a message Aito has not seen.
- 7 test messages also occur word for word in the training split. They are left
  out of scoring (3,073 scored).
- The LLM arms run on a **stratified sample**: 8 test messages per intent, 616 in
  all, drawn with a fixed seed. Every arm is scored on those same 616, so each
  comparison is paired. Aito also runs on all 3,073, since it spends no LLM tokens.

## The arms

| arm | what decides | what it is given |
|---|---|---|
| `aito` | Aito `_predict` | the message; its training data is the 10,003 labelled messages |
| `llm_zero.<model>` | the LLM | the 77 intent labels and the message |
| `llm_rag.<model>` | the LLM | the labels, the message, and the 10 most similar training messages with their intents (text-embedding-3-large, 256 dimensions, cosine) |
| `aito_llm.<model>` | the LLM | the labels, the message, Aito's top 5 intents with their probabilities, and the words behind the top one (`$why`); it may overrule Aito |
| gated | Aito, or `aito_llm` when Aito's probability is below a threshold | the threshold is chosen on one half of the sample and scored on the other |

Models: gpt-5-mini and gpt-5.4 (Azure OpenAI). The prompts are in `run.py`.

## What is measured

- **Accuracy** per arm, with 95% Wilson intervals.
- **Paired difference against Aito only:** McNemar's exact test on the same
  queries, with the Bonferroni threshold for the number of comparisons. A p above
  that threshold is not a shown difference.
- **LLM tokens and spend** per query. Spend is shown only for models with a
  listed price (`llm.py`), and it is LLM spend only. Aito has its own compute and
  licence cost, so an arm without an LLM has "no LLM spend", not "$0".
- **Latency**, median and 95th percentile, per query from the machine that ran it.
  Aito's calls run one at a time. LLM time excludes rate-limit backoff, which is
  reported separately. The RAG arm counts its query-embedding call but not the
  vector search, which ran in pure Python here and takes milliseconds in a vector
  database.
- **Calibration** of Aito's probability on the full test set: the expected
  calibration error, and stated vs actual accuracy per bin.

## Reproduce it

You need an Aito database (`AITO_API_URL`, `AITO_API_KEY` with write access for
the load) and an LLM endpoint: Azure OpenAI (`OPENAI_MODEL_URL`,
`OPENAI_MODEL_API_KEY`, with deployments named after the models) or OpenAI
(`OPENAI_API_KEY`). The variables can go in a `.env` file at the repo root.

```bash
python3 scripts/bench_banking77/fetch.py                                           # data, checksummed
uv run --with 'aitoai>=1.0' python scripts/bench_banking77/load.py --apply         # train split into Aito
./do bench-banking77 gpt-5-mini gpt-5.4                                            # embed, run every arm, summarize
```

`load.py` without `--apply` is a dry run. By default it writes one collection,
`banking77_train`, into a branch environment `banking77`, and refuses master
unless you pass `--master` (for a database of your own). Runs are resumable:
re-running `./do bench-banking77` continues where it stopped. The run files keep
every answer, so any number can be recomputed or re-cut without calling a model
again.

## Caveats

- One public dataset, one domain (banking), one language (English), short messages.
- Two LLMs, one prompt each, no fine-tuning. A fine-tuned classifier is a
  different comparison and is not run here.
- Latency depends on where it is measured from; the results file says where.
