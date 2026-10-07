# Pre-registration: the OpenAI Decisions API arm

Written and committed 2026-10-07, **before any call to `/v1/decisions`**. The harness, splits and
seeds are the ones the existing rows used; nothing about them changes.

## What is added

Two arms, on banking77 (616 queries, 77 intents) and CLINC150 in-scope (600 queries, 150 intents),
on the same stratified samples as every other arm (`SEED = 77`):

- `decisions_zero.gpt-6-luna`: one `choice` question whose choices are the intent labels, input =
  the message. The counterpart of `llm_zero.gpt-6-luna`.
- `decisions_rag.gpt-6-luna`: the same, with the 10 nearest training queries (the same
  text-embedding-3-large retriever) in the input. The counterpart of `llm_rag.gpt-6-luna`.

The question instruction is `Which one intent does this message from <domain> express?` (`run.py`).
The label list is sent as the question's `choices` (value only; no descriptions). Request and response
shapes are those of https://developers.openai.com/api/docs/guides/decisions as read on 2026-10-07.
The stated probability is the answer's `confidence`.

## Expectations written down first (each can be wrong)

1. Accuracy: `decisions_*` lands within the noise of the matching `llm_*.gpt-6-luna` arm (same model,
   different interface). A shown difference is exact McNemar p < 0.05.
2. Against Aito: on banking77 and CLINC150 text understanding, the RAG variants are expected to be
   ahead of Aito alone, as `llm_rag` already is. Where that holds it is reported as the Decisions API
   (or LLM + RAG) winning.
3. Latency and cost: reported as measured. OpenAI's own claim (about 150 ms) is not assumed.
4. Calibration: no expectation of direction. OpenAI publishes none; we report the ECE of `confidence`
   next to Aito's `$p` on the same queries.

## What is reported (all of it, wins and losses)

Accuracy with 95% Wilson intervals; exact McNemar against `aito` and against the matching
`llm_*.gpt-6-luna` arm (Bonferroni over the comparisons made); ECE and stated-vs-right per bin on the
sample (`calibration_on_sample`; Aito's ECE on the full test split is reported as before); latency p50/p95
from the same workstation, labelled; input tokens per query and cost per 1M decisions at the listed
price ($0.10 per 1M input tokens, output not charged). Tokens are read from the response when it has a
`usage` field, otherwise estimated from the request (o200k_base) and flagged per answer.

## Not done here

No gate and no pass/fail rule: this is a comparison, not a test of a claim. No tuning of the
instruction or the choices after seeing results; if the first smoke call shows the request shape
needs a change (for example required choice descriptions), the change is made once, recorded here, and
applied to every query. Answers that error are retried on the next run, never dropped.
