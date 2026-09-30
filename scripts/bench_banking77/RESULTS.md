# banking77: results (2026-09-30)

The numbers below are copied from `results/banking77.json`, which is the source;
the per-query answers are in `results/runs/`. Setup and method: README.md.

**Setup in one line:** banking77 (PolyAI, CC BY 4.0), 77 intents, 10,003 training
messages loaded into Aito; every arm scored on the same 616 test messages (8 per
intent) that Aito never saw; gpt-5-mini, gpt-5.4 and gpt-6-luna on Azure OpenAI
(gpt-6-luna added after the first results); Aito
2.11.0 on shared.aito.ai; latency from the maintainer's workstation (not a
neutral client).

## Accuracy, tokens and latency (616 paired queries)

| arm | accuracy (95% CI) | LLM tokens / query | latency p50 · p95 |
|---|---|---|---|
| Aito only | 84.1% (81.0–86.8) | 0 | 0.07 s · 0.12 s |
| LLM alone, gpt-5-mini | 78.2% (74.8–81.3) | 493 | 1.9 s · 3.7 s |
| LLM alone, gpt-5.4 | 84.7% (81.7–87.4) | 500 | 1.3 s · 2.8 s |
| LLM alone, gpt-6-luna | 83.3% (80.1–86.0) | 502 | 0.87 s · 1.4 s |
| Aito shortlist + $why → LLM, gpt-5-mini | 86.9% (84.0–89.3) | 579 | 2.0 s · 3.6 s |
| Aito shortlist + $why → LLM, gpt-5.4 | 91.2% (88.7–93.2) | 587 | 1.3 s · 2.8 s |
| Aito shortlist + $why → LLM, gpt-6-luna | 89.6% (87.0–91.8) | 586 | 0.89 s · 1.7 s |
| LLM + RAG (10 similar messages), gpt-5-mini | 94.5% (92.4–96.0) | 684 | 1.9 s · 3.5 s |
| LLM + RAG (10 similar messages), gpt-5.4 | 95.1% (93.1–96.6) | 692 | 1.3 s · 2.4 s |
| LLM + RAG (10 similar messages), gpt-6-luna | 94.6% (92.6–96.2) | 686 | 0.90 s · 1.7 s |

LLM spend per 1,000 queries at gpt-5-mini's list price: $0.20 alone, $0.21 with
Aito's shortlist, $0.22 with RAG. gpt-5.4 and gpt-6-luna have no listed price
here, so only their tokens are reported. Aito has no LLM spend (it has its own compute and licence
cost).

**Paired against Aito only** (McNemar exact; 9 comparisons now that gpt-6-luna is
in, so p < 0.0056 is a shown difference):

- LLM + RAG beats Aito with all three models (p < 0.001).
- Aito's shortlist → gpt-5.4 or gpt-6-luna beats Aito (p < 0.001). With gpt-5-mini,
  the gain (+2.8 points) is not shown (p 0.10).
- Aito beats gpt-5-mini alone (p 0.003).
- Aito is level with gpt-5.4 alone (p 0.78) and gpt-6-luna alone (p 0.72).

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
| Aito, else shortlist → gpt-6-luna (model added later) | 89.0% | 88.3% | 50% | 0.19 s · 1.7 s |
| Aito, else RAG → gpt-5-mini (**post hoc**) | 93.2% | 93.5% | 50% | 0.19 s · 3.3 s |
| Aito, else RAG → gpt-5.4 (**post hoc**) | 93.2% | 93.8% | 40% | 0.09 s · 2.3 s |
| Aito, else RAG → gpt-6-luna (**post hoc**) | 93.2% | 93.2% | 50% | 0.19 s · 1.6 s |

No gate is distinguishable from its fallback alone (paired p 0.18–1.0). So a
gate keeps the LLM's accuracy while 50–60% of messages are answered by Aito in
under 0.2 s, with no LLM tokens. The Aito-then-RAG gates were added after the
first results were seen. **The pre-registered test on CLINC150 did not confirm
them** (see below): there, the gate cost 2.3 points of accuracy against RAG.

## How to read it

- On this public benchmark, **the most accurate setup is an LLM with retrieval**,
  not Aito alone. That differs from our synthetic support desk, where Aito
  alone came out ahead. Real data, real result.
- Aito alone is as accurate as a large LLM on its own here (gpt-5.4, gpt-6-luna),
  12–20× faster at the median, with no LLM tokens, and more accurate than
  gpt-5-mini alone. **That last point does not hold on CLINC150** (below).
- Aito's calibrated confidence is what makes the combination work: it knows
  which 50–60% it will get right.
- Handing the LLM Aito's shortlist helps a strong model, but less than handing it
  similar past examples does.

Caveats: one dataset, one domain, English, short messages; one prompt per arm; no
fine-tuned classifier in the comparison; latency from one workstation.

# CLINC150: the pre-registered test (2026-09-30)

Source: `results/clinc150/clinc150.json`. The gate rule and the pass criteria
were committed before any CLINC150 run (PREREGISTRATION.md, gate_rule.json).
CLINC150 (Larson et al. 2019, CC BY 3.0), 150 in-scope intents, 15,000 training
queries in Aito, 600 paired test queries (4 per intent; 2 test texts that also
occur in train were excluded); Aito 2.11.0; gpt-5.4 on Azure OpenAI (the
pre-registered arms). gpt-5-mini and gpt-6-luna were added afterwards, on the
same sample and arms; their gates are not pre-registered.

| arm (600 paired queries) | accuracy (95% CI) | LLM tokens / query | latency p50 · p95 |
|---|---|---|---|
| Aito only | 86.5% (83.5–89.0) | 0 | 0.07 s · 0.11 s |
| gpt-5.4 alone | 95.0% (93.0–96.5) | 585 | 1.3 s · 2.6 s |
| gpt-5.4 + RAG | 98.3% (97.0–99.1) | 737 | 1.3 s · 2.1 s |
| gpt-5-mini alone (added) | 92.3% (89.9–94.2) | 568 | 1.8 s · 3.8 s |
| gpt-6-luna alone (added) | 94.0% (91.8–95.6) | 582 | 0.83 s · 1.3 s |
| Aito shortlist → gpt-5-mini (added) | 94.5% (92.4–96.1) | 651 | 2.1 s · 3.5 s |
| Aito shortlist → gpt-6-luna (added) | 95.7% (93.7–97.0) | 658 | 0.85 s · 1.4 s |
| gpt-5-mini + RAG (added) | 97.3% (95.7–98.4) | 726 | 1.9 s · 3.5 s |
| gpt-6-luna + RAG (added) | 98.2% (96.8–99.0) | 731 | 0.88 s · 1.3 s |

Every LLM arm beats Aito alone here (8 comparisons, all p < 0.001), **including
gpt-5-mini alone** (92.3% vs 86.5%, p < 0.001). On banking77 the small model lost
to Aito; on CLINC150 it wins. On all 4,498 in-scope test queries,
Aito is right 87.8% of the time, the answer is in its top 5 for 97.5%, and its
calibration error is 0.020. 70.5% of queries get p ≥ 0.9, and those are 97.5% right.

**Pre-registered verdict: not confirmed.** The frozen rule picked the threshold
0.9 on the fit half. On the scoring half (300 queries):

- **Calls saved: yes.** 27% of queries called the LLM (the limit was 60%). Median
  latency was 0.07 s.
- **Accuracy kept: no.** The gate scored 95.3%, RAG alone 97.7%: 2.3 points lower
  (95% CI −4.0 to −0.6). RAG was right on 7 queries where the gate was wrong, and
  never the other way round (McNemar p 0.016).

The gate matched gpt-5.4 alone on the same queries (95.3% vs 95.3%, p 1.0) while
calling the LLM on 27% of them.

The same frozen rule on the added models (not pre-registered) points the same
way. With a RAG fallback, the gate scored 95.3% against RAG alone's 97.3%
(gpt-5-mini, p 0.07) and 97.7% (gpt-6-luna, p 0.04). With a shortlist fallback:
92.7% vs 94.3% (gpt-5-mini) and 93.7% vs 95.0% (gpt-6-luna), p 0.18 and 0.29.

## What the two datasets say together

- **An LLM with retrieval is the most accurate setup on both**, with every model
  (banking77 94.5–95.1%, CLINC150 97.3–98.3%).
- **Aito alone vs an LLM alone depends on the dataset.** On banking77 Aito is level
  with gpt-5.4 and gpt-6-luna and beats gpt-5-mini; on CLINC150 every LLM, gpt-5-mini
  included, beats it by 5.8–8.5 points.
- **Aito alone** answers in about 70 ms with no LLM tokens; the fastest LLM here,
  gpt-6-luna, takes about 0.85 s. It is well calibrated
  on both (ECE 0.018 and 0.020), and it is sure (p ≥ 0.9) on 61–71% of queries
  with 97.5–97.7% accuracy on those.
- **An Aito gate in front of RAG costs accuracy.** banking77's post-hoc finding
  that it keeps RAG's accuracy did not replicate: on CLINC150 it lost 2.3 points
  while cutting LLM calls by 73%. Whether that trade is worth it depends on the
  cost of a call and of an error; the data does not decide it.
