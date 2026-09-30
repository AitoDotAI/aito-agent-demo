# banking77: results (2026-09-30)

The numbers below are copied from `results/banking77.json`, which is the source;
the per-query answers are in `results/runs/`. Setup and method: README.md.

**Setup in one line:** banking77 (PolyAI, CC BY 4.0), 77 intents, 10,003 training
messages loaded into Aito; every arm scored on the same 616 test messages (8 per
intent) that Aito never saw; gpt-5-mini and gpt-5.4 on Azure OpenAI; Aito
2.11.0 on shared.aito.ai; latency from the maintainer's workstation (not a
neutral client).

## Accuracy, tokens and latency (616 paired queries)

| arm | accuracy (95% CI) | LLM tokens / query | latency p50 · p95 |
|---|---|---|---|
| Aito only | 84.1% (81.0–86.8) | 0 | 0.07 s · 0.12 s |
| LLM alone, gpt-5-mini | 78.2% (74.8–81.3) | 493 | 1.9 s · 3.7 s |
| LLM alone, gpt-5.4 | 84.7% (81.7–87.4) | 500 | 1.3 s · 2.8 s |
| Aito shortlist + $why → LLM, gpt-5-mini | 86.9% (84.0–89.3) | 579 | 2.0 s · 3.6 s |
| Aito shortlist + $why → LLM, gpt-5.4 | 91.2% (88.7–93.2) | 587 | 1.3 s · 2.8 s |
| LLM + RAG (10 similar messages), gpt-5-mini | 94.5% (92.4–96.0) | 684 | 1.9 s · 3.5 s |
| LLM + RAG (10 similar messages), gpt-5.4 | 95.1% (93.1–96.6) | 692 | 1.3 s · 2.4 s |

LLM spend per 1,000 queries at gpt-5-mini's list price: $0.20 alone, $0.21 with
Aito's shortlist, $0.22 with RAG. gpt-5.4 has no listed price here, so only its
tokens are reported. Aito has no LLM spend (it has its own compute and licence
cost).

**Paired against Aito only** (McNemar exact; 6 comparisons, so p < 0.0083 is a
shown difference):

- LLM + RAG beats Aito with both models (p < 0.001).
- Aito's shortlist → gpt-5.4 beats Aito (p < 0.001). With gpt-5-mini, the gain
  (+2.8 points) is not shown (p 0.10).
- Aito beats gpt-5-mini alone (p 0.003).
- Aito and gpt-5.4 alone are level (p 0.78).

## What Aito's confidence buys

On all 3,073 test messages, Aito is right 84.9% of the time, and its answer is
in its own top 5 for 97.4%. Its probability is well calibrated (expected
calibration error 0.018; below p 0.7 it is slightly under-confident, the safe
direction). 61% of messages get p ≥ 0.9, and those are 97.7% right.

That makes a gate: Aito answers when it is sure, and the LLM answers the rest.
The threshold is chosen on one half of the sample and scored on the other (308
queries).

| gate (scored on the held-out half) | accuracy | its fallback alone | queries calling the LLM | latency p50 · p95 |
|---|---|---|---|---|
| Aito, else shortlist → gpt-5-mini (planned) | 87.7% | 85.7% | 40% | 0.09 s · 3.4 s |
| Aito, else shortlist → gpt-5.4 (planned) | 90.3% | 90.3% | 50% | 0.19 s · 2.7 s |
| Aito, else RAG → gpt-5-mini (**post hoc**) | 93.2% | 93.5% | 50% | 0.19 s · 3.3 s |
| Aito, else RAG → gpt-5.4 (**post hoc**) | 93.2% | 93.8% | 40% | 0.09 s · 2.3 s |

No gate is distinguishable from its fallback alone (paired p 0.18–1.0). So a
gate keeps the LLM's accuracy while 50–60% of messages are answered by Aito in
under 0.2 s, with no LLM tokens. The Aito-then-RAG gates were added after the
first results were seen, so treat them as a finding to confirm on another
dataset, not as a pre-registered result.

## How to read it

- On this public benchmark, **the most accurate setup is an LLM with retrieval**,
  not Aito alone. That differs from our synthetic support desk, where Aito
  alone came out ahead. Real data, real result.
- Aito alone is as accurate as a large LLM on its own (gpt-5.4), about 20× faster
  at the median, with no LLM tokens.
- Aito's calibrated confidence is what makes the combination work: it knows
  which 50–60% it will get right.
- Handing the LLM Aito's shortlist helps a strong model, but less than handing it
  similar past examples does.

Caveats: one dataset, one domain, English, short messages; one prompt per arm; no
fine-tuned classifier in the comparison; latency from one workstation.
