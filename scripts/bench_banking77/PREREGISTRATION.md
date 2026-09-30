# Pre-registration: the Aito-gated RAG result on a second dataset

Written and committed 2026-09-30, **before any CLINC150 data is loaded into Aito
or any model is run on it**. On banking77, the Aito-gated RAG arm was added after
the first results were seen (RESULTS.md labels it post hoc). This file fixes the
rule and the test in advance, so the second dataset can confirm or refute it.

## The claim under test

An Aito gate in front of an LLM + RAG classifier (Aito answers when its $p
clears a threshold; otherwise the LLM + RAG answers) keeps RAG's accuracy while
the LLM is called on only part of the queries.

## The dataset

CLINC150 (Larson et al., 2019), `data_full.json` from
https://github.com/clinc/oos-eval, licence CC BY 3.0, pinned by sha256
`36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`.

- 150 in-scope intents. Aito loads the 15,000 in-scope training queries; the
  test queries are never loaded.
- Scored: the in-scope test split (4,500, 30 per intent). Test texts that also
  occur in the training split are excluded, and the count is reported.
- The out-of-scope queries (`oos_*`) are not part of this test. They go into a
  separate, later analysis, and are not used to tune anything here.
- The LLM arms run on a stratified sample of 4 test queries per intent (600),
  drawn with seed 77, the same procedure as banking77's.

## The arms (all on the same 600)

- `aito`: `_predict intent` from the text, top 5 with $p.
- `llm_rag.gpt-5.4`: the 150 labels, the message, and the 10 nearest training
  queries by text-embedding-3-large (256 dimensions) cosine similarity.
- `llm_zero.gpt-5.4`: the 150 labels and the message (for context).
- The gate: derived from `aito` and `llm_rag.gpt-5.4`, with no calls of its own.

The prompts are those in `run.py` at this commit.

## The gate rule (frozen: `gate_rule.json`)

1. Shuffle the 600 sampled query ids with `random.Random(77)`. The first half is
   the fit half; the second half is the scoring half.
2. On the fit half, for each threshold in 0.30, 0.35, ..., 0.95, count the queries
   right when the answer is Aito's if $p ≥ threshold, else the RAG arm's.
3. Pick the threshold with the most right answers; on a tie, the lower threshold.
4. Score that threshold once on the scoring half.

## What counts as confirming

Both of these, on the scoring half:

- **Accuracy kept:** the gate's accuracy is not below RAG alone's on the same
  queries by a shown difference. That means exact McNemar, two-sided, p < 0.05,
  with RAG right more often. The upper end of the gate-minus-RAG difference is
  reported with its 95% interval.
- **Calls saved:** the share of scoring-half queries that call the LLM is at most
  0.60.

If either fails, the result is reported as not confirmed, with its numbers. The
banking77 post-hoc result keeps its post-hoc label either way.

## Also reported, not pre-registered

Every arm's accuracy with a 95% Wilson interval, paired McNemar against Aito,
tokens, LLM spend where a list price is known, p50/p95 latency (from the same
workstation as banking77, labelled), and Aito's calibration on the full in-scope
test split.

## Addendum (2026-09-30, still before any CLINC150 run)

The prompts' one dataset-specific phrase is now a per-dataset setting in
`common.py`. The system prompt names the source of the message ("a bank's
support chat" for banking77; "a user of a general-purpose virtual assistant" for
CLINC150), and the shortlist arm says "This bank's" or "This assistant's"
history. banking77's prompts are byte-identical to the ones its results were
recorded with (checked), and its results file is unchanged. Nothing else in the
plan above changes. The harness runs CLINC150 with `BENCH_DATASET=clinc150`.
