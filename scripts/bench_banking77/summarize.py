"""Turn the run files into results/banking77.json: the one file the benchmark page reads.

Every arm is scored on the same stratified sample (8 queries per intent), so the
comparisons are paired: McNemar's exact test against Aito only, with the
Bonferroni threshold for the number of comparisons made. Accuracy has 95%
Wilson intervals. The gated arm's threshold is chosen on one half of the sample
and scored on the other, so it is not fitted to the queries it is scored on.

    python3 scripts/bench_banking77/summarize.py
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
from datetime import datetime, timezone

from common import RESULTS, SEED, ece, jsonl, labels, mcnemar, pct, sample, share, split
from llm import PRICES

RUNS = RESULTS / "runs"
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(14)]   # 0.30 .. 0.95


def arm_stats(rows: list[dict], qids: list[str]) -> dict:
    rs = [rows[q] for q in qids]
    right = [r["pred"] == r["gold"] for r in rs]
    out = {**share(right),
           "latency_ms": {"p50": pct([r["ms"] for r in rs], 0.5), "p95": pct([r["ms"] for r in rs], 0.95),
                          "mean": round(st.mean(r["ms"] for r in rs), 1)}}
    if "in" in rs[0]:
        tin, tout = sum(r["in"] for r in rs), sum(r["out"] for r in rs)
        costs = [r["usd"] for r in rs]
        out["llm"] = {"calls_per_query": 1.0, "tokens_per_query": round((tin + tout) / len(rs)),
                      "input_tokens_per_query": round(tin / len(rs)), "output_tokens_per_query": round(tout / len(rs)),
                      "usd_per_1000_queries": None if any(c is None for c in costs) else round(sum(costs) / len(rs) * 1000, 3),
                      "invalid_label_answers": sum(r["pred"] is None for r in rs),
                      "rate_limit_backoff_ms_total": sum(r.get("backoff_ms", 0) for r in rs)}
    else:
        out["llm"] = {"calls_per_query": 0.0, "tokens_per_query": 0, "usd_per_1000_queries": 0.0}
    return out


def gated(aito: dict, coop: dict, qids: list[str], tau: float) -> list[bool]:
    return [(aito[q]["pred"] if aito[q]["p"] >= tau else coop[q]["pred"]) == aito[q]["gold"] for q in qids]


def main() -> int:
    train, test, dropped = split()
    picked = [q["qid"] for q in sample(test)]
    aito = jsonl(RUNS / "aito.jsonl")
    full = jsonl(RUNS / "aito_full.jsonl")
    missing = [q for q in picked if q not in aito]
    if missing:
        sys.exit(f"aito.jsonl lacks {len(missing)} sampled queries: run run.py first")

    arms = {"aito": aito}
    for path in sorted(RUNS.glob("*.*.jsonl")):
        rows = jsonl(path)
        if all(q in rows for q in picked):
            arms[path.stem] = rows
        else:
            print(f"skipping {path.name}: {sum(q in rows for q in picked)} of {len(picked)} sampled queries done")

    out = {
        "benchmark": "banking77 intent classification (77 intents), Aito vs LLMs, paired on one sample",
        "dataset": {"name": "banking77", "source": "PolyAI, https://github.com/PolyAI-LDN/task-specific-datasets",
                    "license": "CC BY 4.0", "train": len(train), "test": len(test) + dropped,
                    "test_scored": len(test), "excluded_test_texts_also_in_train": dropped,
                    "labels": len(labels(train))},
        "sample": {"per_intent": len(picked) // len(labels(train)), "n": len(picked), "seed": SEED,
                   "note": "every arm is scored on these same queries, so the comparisons are paired"},
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "arms": {name: arm_stats(rows, picked) for name, rows in arms.items()},
    }
    if len(full) >= len(test):
        rs = list(full.values())
        out["aito_full_test"] = {**share([r["pred"] == r["gold"] for r in rs]),
                                 "top5_contains_answer": share([r["gold"] in [t["intent"] for t in r["top"]] for r in rs]),
                                 "calibration": ece([(r["p"], r["pred"] == r["gold"]) for r in rs])}

    others = [a for a in arms if a != "aito"]
    out["paired_vs_aito"] = {a: mcnemar([aito[q]["pred"] == aito[q]["gold"] for q in picked],
                                        [arms[a][q]["pred"] == arms[a][q]["gold"] for q in picked]) for a in others}
    if others:
        out["paired_vs_aito"]["bonferroni_threshold"] = round(0.05 / len(others), 5)
        out["paired_vs_aito"]["note"] = ("only_first_right = Aito right, the other wrong. A p below the threshold "
                                         "is a difference at this n; above it, it is not shown.")

    # gated: fit the threshold on one half, score it on the other
    order = picked[:]
    random.Random(SEED).shuffle(order)
    fit, hold = sorted(order[: len(order) // 2]), sorted(order[len(order) // 2:])
    out["gated"] = {}
    for name, coop in arms.items():
        if not name.startswith("aito_llm."):
            continue
        best = max(THRESHOLDS, key=lambda t: (sum(gated(aito, coop, fit, t)), -t))
        right = gated(aito, coop, hold, best)
        calls = sum(aito[q]["p"] < best for q in hold) / len(hold)
        out["gated"][name.replace("aito_llm.", "")] = {
            "threshold_fit_on": len(fit), "threshold": best, "scored_on": len(hold), **share(right),
            "share_calling_llm": round(calls, 3),
            "aito_only_same_half": share([aito[q]["pred"] == aito[q]["gold"] for q in hold]),
            "paired_vs_aito_same_half": mcnemar([aito[q]["pred"] == aito[q]["gold"] for q in hold], right)}

    out["prices"] = PRICES
    emb = RESULTS / "embedding.json"
    if emb.exists():
        out["rag_retriever"] = {**json.loads(emb.read_text()), "k": 10,
                                "latency_note": ("the RAG arm's latency counts the query's embedding call and the "
                                                 "LLM call; the vector search itself ran in pure Python here and is "
                                                 "left out, since a vector database does it in milliseconds")}
    out["latency_note"] = ("wall time per query from the machine that ran run.py; Aito's calls ran one at a time, "
                           "the LLM's with --workers in parallel, each timed on its own. LLM time excludes "
                           "rate-limit backoff, which is reported per arm")
    out["cost_note"] = ("LLM spend only, at the listed prices. Aito has its own compute and licence cost, which "
                        "is not LLM spend; say 'no LLM spend / 0 tokens', never '$0'")
    (RESULTS / "banking77.json").write_text(json.dumps(out, indent=1) + "\n")
    for name, a in out["arms"].items():
        print(f"{name:28} {a['accuracy']:.3f} {a['ci95']}  tokens {a['llm']['tokens_per_query']:>5}  "
              f"p50 {a['latency_ms']['p50']} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
