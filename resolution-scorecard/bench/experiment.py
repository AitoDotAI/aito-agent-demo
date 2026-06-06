"""Run the resolution scorecard: Aito (predict-first) vs the LLM agent, scored on
better / faster / cheaper across the four resolution paths.

    python -m bench.experiment
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict

from aito.client import AitoClient
from bench import config
from bench.llm import LLMAgent


def _gold_param(t: dict):
    return t["target_service"] or t["location"] or t["kb_article"]  # None for check_balance


def _sample(test: list[dict], n: int) -> list[dict]:
    by_intent = defaultdict(list)
    for t in test:
        by_intent[t["intent"]].append(t)
    per = max(1, n // len(by_intent))
    out = []
    for intent in config.INTENTS:
        out += by_intent[intent][:per]
    return out[:n]


def run_aito(aito: AitoClient, tickets: list[dict]) -> list[dict]:
    out = []
    for t in tickets:
        where = {"text": t["text"], "sender_domain": t["sender_domain"]}
        ri = aito.predict("intent", where)
        pf = config.INTENT_PARAM.get(ri.feature)
        lat = ri.latency_ms
        pv, pp = None, 1.0
        if pf:
            rp = aito.predict(pf, where)
            pv, pp = rp.feature, rp.p
            lat += rp.latency_ms
        out.append({"id": t["id"], "gold_intent": t["intent"], "gold_param": _gold_param(t),
                    "pred_intent": ri.feature, "pred_param": pv,
                    "p_intent": ri.p, "p_param": pp, "latency_ms": lat})
    return out


def run_llm(agent: LLMAgent, tickets: list[dict], log) -> list[dict]:
    out = []
    for t in tickets:
        r = agent.resolve(t["text"])
        f = r.fields
        pf = config.INTENT_PARAM.get(f.get("intent"))
        pv = f.get(pf) if pf else None
        out.append({"id": t["id"], "gold_intent": t["intent"], "gold_param": _gold_param(t),
                    "pred_intent": f.get("intent"), "pred_param": pv,
                    "in_tok": r.input_tokens, "out_tok": r.output_tokens, "latency_ms": r.latency_ms})
        log.write(json.dumps({"id": t["id"], "op": "llm.resolve", **r.fields,
                              "in_tok": r.input_tokens, "out_tok": r.output_tokens,
                              "latency_ms": round(r.latency_ms, 1)}) + "\n")
        log.flush()
    return out


def score(recs: list[dict]) -> dict:
    n = len(recs)
    intent_ok = sum(r["pred_intent"] == r["gold_intent"] for r in recs)
    e2e_ok = sum(r["pred_intent"] == r["gold_intent"] and r["pred_param"] == r["gold_param"] for r in recs)
    # param accuracy given the intent was right and the intent needs a param
    needs = [r for r in recs if r["gold_param"] is not None and r["pred_intent"] == r["gold_intent"]]
    param_ok = sum(r["pred_param"] == r["gold_param"] for r in needs)
    lat = [r["latency_ms"] for r in recs]
    out = {
        "n": n,
        "intent_acc": intent_ok / n,
        "end_to_end_acc": e2e_ok / n,
        "param_acc_given_intent": (param_ok / len(needs)) if needs else None,
        "latency_ms_p50": statistics.median(lat),
        "latency_ms_mean": statistics.mean(lat),
    }
    # per-intent end-to-end
    by = defaultdict(lambda: [0, 0])
    for r in recs:
        ok = r["pred_intent"] == r["gold_intent"] and r["pred_param"] == r["gold_param"]
        by[r["gold_intent"]][0] += ok; by[r["gold_intent"]][1] += 1
    out["per_intent"] = {k: round(v[0] / v[1], 3) for k, v in by.items()}
    return out


def main() -> None:
    train = json.loads((config.DATA_DIR / "train.json").read_text())
    test = json.loads((config.DATA_DIR / "test.json").read_text())
    sample = _sample(test, config.LLM_SAMPLE)
    config.RESULTS_DIR.mkdir(exist_ok=True)
    print(f"train={len(train)} test={len(test)} llm_sample={len(sample)}")

    with AitoClient() as aito:
        n_up = aito.recreate_and_upload(train)
        print(f"uploaded {n_up} TRAIN rows; running Aito on {len(test)} test...")
        t0 = time.perf_counter()
        aito_full = run_aito(aito, test)
        print(f"  aito full done in {time.perf_counter()-t0:.0f}s")
        aito_sample = run_aito(aito, sample)

    print(f"running LLM agent on {len(sample)} sample tickets (rate-limited)...")
    agent = LLMAgent()
    with open(config.CALLS_LOG, "w") as log:
        llm_sample = run_llm(agent, sample, log)

    s_aito_full = score(aito_full)
    s_aito_sample = score(aito_sample)
    s_llm = score(llm_sample)

    in_tok = sum(r["in_tok"] for r in llm_sample); out_tok = sum(r["out_tok"] for r in llm_sample)
    llm_cost_per_res = config.cost_usd(in_tok, out_tok) / len(llm_sample)

    result = {
        "model": config.load_llm_config().model_name,
        "n_test": len(test), "n_llm_sample": len(sample),
        "price_in_per_mtok": config.PRICE_INPUT_USD_PER_MTOK, "price_out_per_mtok": config.PRICE_OUTPUT_USD_PER_MTOK,
        "aito_full": s_aito_full,
        "aito_on_sample": s_aito_sample,
        "llm_on_sample": s_llm,
        "llm_tokens_per_resolution": (in_tok + out_tok) / len(sample),
        "llm_cost_per_resolution_usd": llm_cost_per_res,
        "llm_cost_per_1000_usd": llm_cost_per_res * 1000,
        "aito_cost_per_1000_usd": 0.0,
        "aito_auto_resolve_rate": sum(
            1 for r in aito_full if r["p_intent"] >= config.GATE and r["p_param"] >= config.GATE
        ) / len(aito_full),
        "gate": config.GATE,
    }
    (config.RESULTS_DIR / "scorecard.json").write_text(json.dumps(result, indent=2))
    print("\n=== SCORECARD ===")
    print(f"BETTER  end-to-end acc: aito(full)={s_aito_full['end_to_end_acc']:.3f} "
          f"aito(sample)={s_aito_sample['end_to_end_acc']:.3f} llm(sample)={s_llm['end_to_end_acc']:.3f}")
    print(f"FASTER  p50 latency/resolution: aito={s_aito_full['latency_ms_p50']:.0f}ms llm={s_llm['latency_ms_p50']:.0f}ms")
    print(f"CHEAPER $/1000 resolutions: aito=$0.00 llm=${result['llm_cost_per_1000_usd']:.2f} "
          f"({result['llm_tokens_per_resolution']:.0f} tok/resolution)")
    print(f"AUTO    aito auto-resolve rate (gate {config.GATE}): {result['aito_auto_resolve_rate']:.2f}")
    print("wrote scorecard.json")


if __name__ == "__main__":
    main()
