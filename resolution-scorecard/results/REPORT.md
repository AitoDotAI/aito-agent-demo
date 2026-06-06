# Resolution scorecard — predictive layer vs LLM agent

**Better · faster · cheaper**, across four resolution paths in one dataset. An LLM
agent resolves a ticket by reasoning and (in a real system) *chaining tool calls*; a
predictive layer turns "understand + resolve + fill the parameter" into a couple of
`_predict` calls answered from history — escalating only the unsure ones.

LLM agent: **gpt-5-mini** (Azure OpenAI), one structured call/ticket — a *generous* baseline
(a real tool-calling agent chains several round-trips). Aito scored on all 800 test tickets;
the LLM agent measured on 78. LLM priced at $0.25/2.0 per 1M in/out tokens.

## The scorecard
| axis | Aito (predict-first) | LLM agent (gpt-5-mini) |
|---|---|---|
| **better** — end-to-end accuracy | 100% (full 800) | 100% (sample) |
| **faster** — latency / resolution | **148 ms** | ~3.6 s / call |
| **cheaper** — LLM $ / 1000 resolutions | **$0.00** | $0.15 (302 tok/res) |
| **hands-off** — auto-resolved at gate 0.8 | **100%** | n/a (no calibrated abstain) |

**Honest reading: accuracy is a tie (100% vs 100%).** This data is clean enough that
both resolve it perfectly, so *better* isn't the story here — the accuracy/calibration nuances are
in the tool-routing and assignment benchmarks. **Here the win is latency and cost:** ~24× faster
per single resolution, at zero per-ticket LLM cost.

## The real drama is multi-step workflows
The scorecard gives the agent its best case: **one** call. A real resolution is a *chain* —
classify → identify customer → look up the record → fill parameters → confirm — run
**sequentially** at ~3.6s each. Aito fires the equivalent `_predict`s in ~one round-trip.
The gap compounds with workflow length:

| workflow steps | LLM agent (sequential) | Aito |
|---|---|---|
| 1 | 3.6 s | ~0.15 s |
| 3 | 10.8 s | ~0.15 s |
| 6 | 22 s | ~0.15 s |

A six-step flow the agent runs in **~22 seconds** is **effectively instant** with the
predictive layer — and free. For a customer waiting on a reply, that's the difference between a
20-second spinner and an immediate answer.

## Framing: Aito as a predictive cache in front of the LLM ("Redis for LLM")
The cleanest way to narrate this: Aito is a **smart cache** keyed on the ticket + its
structured context, with a *calibrated* confidence.
- **hit** (`$p ≥ gate`) → serve the predicted resolution instantly, ~free — this is the
  auto-resolve rate (100% on this clean data; history- and traffic-dependent in general).
- **miss** (cold start / novel / low confidence) → fall through to the LLM, pay latency + tokens.
- **write-back** → the LLM's answer is logged and is in the *next* prediction (no retrain).
  The cache fills itself from its own misses, so the hit rate **warms up** with history.

A cold cache is 100% miss = plain LLM, **no worse than today** — so this is a Pareto add-on, and
"Aito needs history" simply means "the cache hasn't warmed yet." Blended economics behave like any
cache (effective cost ≈ miss-rate × LLM cost; effective latency ≈ hit-rate × 148ms +
miss-rate × 3.6s):

| cache hit rate | LLM $ / 1000 (= miss × $0.15) | mean latency |
|---|---|---|
| 0% (cold) | $0.15 | 3.6 s |
| 40% | $0.09 | 2.2 s |
| 80% | $0.03 | 0.8 s |
| 95% | $0.01 | 0.32 s |

The honest hard problem is **cache invalidation**: if the right resolution changes (policy/reorg),
stale history can yield a confidently-wrong *hit*. Mitigations: the calibration gate, recency
weighting, TTL-style windows. That — not cold start — is the risk to manage.

## Per-path accuracy (intent + its parameter)
| path | Aito | LLM agent |
|---|---|---|
| cancel_service | 1.00 | 1.00 |
| refund | 1.00 | 1.00 |
| check_outage | 1.00 | 1.00 |
| find_shop | 1.00 | 1.00 |
| repair_help | 1.00 | 1.00 |
| check_balance | 1.00 | 1.00 |

(`cancel_service`/`refund` → **service**; `check_outage`/`find_shop` → **location**;
`repair_help` → **KB article**; `check_balance` → no parameter.)

## Honest caveats
- **Accuracy is a tie on this clean data** — the win demonstrated here is latency & cost, not
  correctness. On messy or novel tickets the accuracy/calibration differences (and Aito's need for
  history) from the other benchmarks apply.
- **Latency caveat:** a clean gpt-5-mini call is ~3.6s; under the shared deployment's rate
  limit, 78 back-to-back calls measured a p50 of ~20s. We headline the conservative ~3.6s
  and do **not** exploit the throttle. Aito's 148ms is the measured round-trip for two `_predict`s.
- **Cost is modest per ticket for a mini model** ($0.15/1000); it grows with workflow
  length, model size (Opus-class is ~40× the token price), and volume — while Aito stays $0 LLM.
- The LLM baseline is a **single structured call** (best case). A real tool-calling agent chains
  round-trips, so its true latency/cost are higher — the gap shown is a lower bound.
- Synthetic, seeded data; phrasing uses aliases, not canonical tokens. The transferable result is the
  **shape**: comparable accuracy, order-of-magnitude less latency and cost, with a calibrated
  auto-resolve slice that needs no LLM at all.
