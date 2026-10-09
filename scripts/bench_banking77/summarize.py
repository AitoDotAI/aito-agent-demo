"""Turn the run files into results/banking77.json: the one file the benchmark page reads.

Every arm is scored on the same stratified sample (8 queries per intent), so the
comparisons are paired: McNemar's exact test against Aito only, with the
Bonferroni threshold for the number of comparisons made. Accuracy has 95%
Wilson intervals. The gated arm's threshold is chosen on one half of the sample
and scored on the other, so it is not fitted to the queries it is scored on.

    uv run python scripts/bench_banking77/summarize.py        (it imports llm.py, which needs openai)
"""

from __future__ import annotations

import json
import os
import random
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import CFG, DATASET, RESULTS, ROOT, SEED, ece, jsonl, labels, mcnemar, pct, sample, share, split
from decisions import DECISIONS_PRICES
from llm import PRICES

RUNS = RESULTS / "runs"
#: our recorded runs (the committed results/), as opposed to someone's rerun into another directory
RECORDED = not os.environ.get("BANKING77_RESULTS")
#: when each dataset's first results were measured (their summaries are re-run as arms are added)
FIRST_MEASURED = {"banking77": "2026-09-30T08:53:00+00:00", "clinc150": "2026-09-30T09:22:14+00:00"}
#: the frozen gate rule (PREREGISTRATION.md); the code below implements exactly it
RULE = json.loads((Path(__file__).resolve().parent / "gate_rule.json").read_text())
THRESHOLDS = RULE["thresholds"]
#: banking77's first run, whose shortlist gates were planned before any result
FIRST_RUN_MODELS = {"gpt-5-mini", "gpt-5.4"}
#: the commit that froze the rule, before any CLINC150 load or model call
PREREG_COMMIT = "f49c5062"


def arm_stats(rows: list[dict], qids: list[str]) -> dict:
    rs = [rows[q] for q in qids]
    right = [r["pred"] == r["gold"] for r in rs]
    out = {**share(right),
           "latency_ms": {"p50": pct([r["ms"] for r in rs], 0.5), "p95": pct([r["ms"] for r in rs], 0.95),
                          "mean": round(st.mean(r["ms"] for r in rs), 1)}}
    # a stated probability (Aito's $p, the Decisions API's confidence) is scored for calibration on these queries
    stated = [(r["p"], ok) for r, ok in zip(rs, right) if r.get("p") is not None]
    if len(stated) >= 0.9 * len(rs):      # a refusal states no probability: scored without it, and counted
        out["calibration_on_sample"] = {**ece(stated), "answers_without_probability": len(rs) - len(stated)}
    if "in" in rs[0]:
        tin, tout = sum(r["in"] for r in rs), sum(r["out"] for r in rs)
        costs = [r["usd"] for r in rs]
        out["llm"] = {"calls_per_query": 1.0, "tokens_per_query": round((tin + tout) / len(rs)),
                      "input_tokens_per_query": round(tin / len(rs)), "output_tokens_per_query": round(tout / len(rs)),
                      "usd_per_1000_queries": None if any(c is None for c in costs) else round(sum(costs) / len(rs) * 1000, 3),
                      "usd_per_1m_decisions": None if any(c is None for c in costs) else round(sum(costs) / len(rs) * 1e6, 2),
                      "tokens_estimated_for": sum(bool(r.get("tokens_estimated")) for r in rs),
                      "invalid_label_answers": sum(r["pred"] is None for r in rs),
                      "rate_limit_backoff_ms_total": sum(r.get("backoff_ms", 0) for r in rs)}
    else:
        out["llm"] = {"calls_per_query": 0.0, "tokens_per_query": 0, "usd_per_1000_queries": None,
                      "llm_spend": "none: no LLM calls (Aito has its own compute and licence cost)"}
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
        "benchmark": f"{DATASET} intent classification ({len(labels(train))} intents), Aito vs LLMs, paired on one sample",
        "dataset": {"name": CFG["title"], "source": CFG["source"],
                    "license": CFG["license"], "train": len(train), "test": len(test) + dropped,
                    "test_scored": len(test), "excluded_test_texts_also_in_train": dropped,
                    "labels": len(labels(train))},
        "sample": {"per_intent": len(picked) // len(labels(train)), "n": len(picked), "seed": SEED,
                   "note": "every arm is scored on these same queries, so the comparisons are paired"},
        "measured_at": (FIRST_MEASURED.get(DATASET) if RECORDED else None) or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summarized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_files_last_written": {p.stem: datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
                                   for p in sorted(RUNS.glob("*.jsonl"))},
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
    random.Random(RULE["split_seed"]).shuffle(order)
    fit, hold = sorted(order[: len(order) // 2]), sorted(order[len(order) // 2:])
    out["gated"] = {}
    # planned: Aito when sure, else Aito's shortlist to the LLM. Added after the first results
    # (post hoc, labelled so): Aito when sure, else LLM + RAG. Neither makes a call of its own.
    for name, coop in arms.items():
        if not name.startswith(("aito_llm.", "llm_rag.")):
            continue
        best = max(THRESHOLDS, key=lambda t: (sum(gated(aito, coop, fit, t)), -t))
        right = gated(aito, coop, hold, best)
        calls = sum(aito[q]["p"] < best for q in hold) / len(hold)
        kind, model = name.split(".", 1)
        out["gated"][f"aito_then_{'shortlist_llm' if kind == 'aito_llm' else 'rag_llm'}.{model}"] = {
            # banking77: the shortlist gate was planned, the RAG gate found after the first results.
            # Elsewhere the gate on the rule's fallback arm was fixed in advance (PREREGISTRATION.md).
            "planned": (kind == "aito_llm" and model in FIRST_RUN_MODELS) if DATASET == "banking77"
                       else name == RULE["clinc150_fallback"],
            "preregistered": (None if DATASET == "banking77" or name != RULE["clinc150_fallback"] else
                              {"file": "PREREGISTRATION.md + gate_rule.json", "commit": PREREG_COMMIT,
                               "addendum_commit": "020a2d2c (the per-dataset prompt phrase)"}),
            "status": ("pre-registered" if DATASET != "banking77" and name == RULE["clinc150_fallback"] else
                       "planned" if DATASET == "banking77" and kind == "aito_llm" and model in FIRST_RUN_MODELS else
                       "post hoc: found after the first results" if DATASET == "banking77" and model in FIRST_RUN_MODELS else
                       "not planned: model added after the first results, same gate rule" if DATASET == "banking77" else
                       "not pre-registered: arm added after the pre-registered run, same frozen gate rule"),
            "threshold_fit_on": len(fit), "threshold": best, "scored_on": len(hold), **share(right),
            "share_calling_llm": round(calls, 3),
            "aito_only_same_half": share([aito[q]["pred"] == aito[q]["gold"] for q in hold]),
            "paired_vs_aito_same_half": mcnemar([aito[q]["pred"] == aito[q]["gold"] for q in hold], right),
            # against the LLM arm it falls back to, alone on the same half: what gating costs in accuracy
            "fallback_alone_same_half": share([coop[q]["pred"] == coop[q]["gold"] for q in hold]),
            "paired_vs_fallback_alone_same_half": mcnemar([coop[q]["pred"] == coop[q]["gold"] for q in hold], right),
            # every arm alone on the same scoring half, paired with the gate
            # (only_first_right = the gate right, the arm wrong)
            "vs_each_arm_same_half": {
                other: {**share([rows[q]["pred"] == rows[q]["gold"] for q in hold]),
                        "paired": mcnemar(right, [rows[q]["pred"] == rows[q]["gold"] for q in hold])}
                for other, rows in arms.items()},
            "vs_each_arm_note": ("descriptive: one paired McNemar per arm, not corrected for the number of "
                                 "comparisons; only_first_right = the gate right, the arm wrong"),
            # the fallback ran after Aito's call: the shortlist arm's time already includes it, RAG's does not
            "median_latency_ms": pct([aito[q]["ms"] if aito[q]["p"] >= best else
                                      coop[q]["ms"] + (aito[q]["ms"] if kind == "llm_rag" else 0) for q in hold], 0.5),
            "p95_latency_ms": pct([aito[q]["ms"] if aito[q]["p"] >= best else
                                   coop[q]["ms"] + (aito[q]["ms"] if kind == "llm_rag" else 0) for q in hold], 0.95)}

    # the pre-registered test (PREREGISTRATION.md, gate_rule.json), on any dataset but banking77
    if DATASET != "banking77":
        fb = RULE["clinc150_fallback"]
        g = out["gated"].get(f"aito_then_rag_llm.{fb.split('.', 1)[1]}") if fb.startswith("llm_rag.") else None
        if g is None:
            out["preregistered_verdict"] = {"status": f"not run: the fallback arm {fb} is incomplete"}
        else:
            m = g["paired_vs_fallback_alone_same_half"]
            worse = m["p"] < 0.05 and m["only_first_right"] > m["only_second_right"]   # the fallback right more often
            n = g["n"]
            diff = (m["only_second_right"] - m["only_first_right"]) / n
            se = ((m["only_first_right"] + m["only_second_right"]) / n - diff ** 2) ** 0.5 / n ** 0.5
            kept, saved = not worse, g["share_calling_llm"] <= RULE["confirm"]["max_share_calling_llm"]
            out["preregistered_verdict"] = {
                "rule": "gate_rule.json", "fallback": fb, "threshold": g["threshold"],
                "accuracy_kept": kept, "calls_saved": saved,
                "gate_minus_fallback": round(diff, 4), "ci95_wald_paired": [round(diff - 1.96 * se, 4), round(diff + 1.96 * se, 4)],
                "share_calling_llm": g["share_calling_llm"],
                "status": "confirmed" if kept and saved else "not confirmed"}

    out["prices"] = PRICES
    out["decisions_prices"] = DECISIONS_PRICES
    emb = RESULTS / "embedding.json"
    if emb.exists():
        out["rag_retriever"] = {**json.loads(emb.read_text()), "k": 10,
                                "latency_note": ("the RAG arm's latency counts the query's embedding call and the "
                                                 "LLM call; the vector search itself ran in pure Python here and is "
                                                 "left out, since a vector database does it in milliseconds")}
    out["latency_client"] = os.environ.get("BENCH_CLIENT") or ("the maintainer's workstation; not a neutral client"
                                                               if RECORDED else "unknown: set BENCH_CLIENT")
    engine = RUNS / "engine.json"
    # recorded by run.py with the answers; a summary needs no credentials
    recorded = json.loads((RUNS / "endpoints.json").read_text()) if (RUNS / "endpoints.json").exists() else {}
    # arms recorded before per-arm tracking share the file's top-level endpoints
    from run import uses
    per_arm = {a: recorded.get("per_arm", {}).get(a, {k: recorded[k] for k in sorted(uses(a)) if k in recorded})
               for a in arms}

    def distinct(key):
        vals = sorted({e[key] for e in per_arm.values() if e.get(key)})
        return vals[0] if len(vals) == 1 else (vals or ["unknown"])
    where = {"aito": distinct("aito"), "llm": distinct("llm"), "decisions": distinct("decisions")}
    out["endpoints"] = {"aito": where["aito"], "per_arm": per_arm, "decisions": where["decisions"],
                        "aito_engine": json.loads(engine.read_text()) if engine.exists() else None,
                        "llm": where["llm"]}
    out["latency_note"] = ("wall time per query from the machine that ran run.py; Aito's calls ran one at a time, "
                           "the LLM's with --workers in parallel, each timed on its own. LLM time excludes "
                           "rate-limit backoff, which is reported per arm")
    out["cost_note"] = ("LLM spend only, at the listed prices. Aito has its own compute and licence cost, which "
                        "is not LLM spend; say 'no LLM spend / 0 tokens', never '$0'")
    (RESULTS / f"{DATASET}.json").write_text(json.dumps(out, indent=1) + "\n")
    for name, a in out["arms"].items():
        print(f"{name:28} {a['accuracy']:.3f} {a['ci95']}  tokens {a['llm']['tokens_per_query']:>5}  "
              f"p50 {a['latency_ms']['p50']} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
