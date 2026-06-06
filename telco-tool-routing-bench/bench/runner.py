"""Run all three configs on the TEST split across the tool-count sweep.

Order of operations:
  1. Ensure thresholds are chosen on VAL (runs bench.select if needed).
  2. For each tool_count: Baseline A (full) + Baseline B (retrieval) on every
     TEST ticket.
  3. Aito ONCE on TEST — its predictions/queries are identical across the sweep
     by construction (it never sees the catalog), so we run it once and the
     report replicates the cell across tool_counts. This is documented as a
     structural property, not an empirical 'win', in REPORT.md.

Every call is logged to results/calls.jsonl. Decisions are persisted to
results/decisions.json for the report step.

    python -m bench.runner            # full run
    python -m bench.runner --limit 8  # smoke run on first 8 TEST tickets/config
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys

from aito.predict import AitoPredictor
from bench import config, select
from bench.aito_agent import resolve_aito
from bench.calls import CallLog
from bench.decision import Decision
from bench.llm import LLMClient
from bench.llm_agent import ToolIndex, resolve_baseline_full, resolve_baseline_retrieval
from data.tools import build_tools


def _load_params() -> dict:
    if not config.CHOSEN_PARAMS.exists():
        print("chosen_params.json missing — running VAL selection first...")
        select.main()
    return json.loads(config.CHOSEN_PARAMS.read_text())


def _log_decision(log: CallLog, d: Decision) -> None:
    for rec in d.call_records:
        log.record(**rec)


DECISIONS_PATH = config.RESULTS_DIR / "decisions.json"


def _running_cost(out: dict) -> float:
    cells = list(out["by_tool_count"].values())
    decs = out["aito"] + [d for c in cells for d in c["baseline_full"] + c["baseline_retrieval"]]
    return config.cost_usd(sum(d["input_tokens"] for d in decs),
                           sum(d["output_tokens"] for d in decs))


def _save(out: dict) -> None:
    """Atomic checkpoint so a rate-limit crash never corrupts decisions.json."""
    tmp = DECISIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False))
    os.replace(tmp, DECISIONS_PATH)


def _init_out(test: list[dict], params: dict, limit) -> dict:
    """Load a prior checkpoint to resume, unless the run shape changed."""
    if DECISIONS_PATH.exists():
        prev = json.loads(DECISIONS_PATH.read_text())
        if prev.get("n_test") == len(test) and prev.get("limit") == limit:
            prev.setdefault("by_tool_count", {})
            prev.setdefault("aito", [])
            prev["params"] = params
            return prev
        print("prior decisions.json has a different run shape — starting fresh")
    return {"by_tool_count": {}, "aito": [], "n_test": len(test), "params": params, "limit": limit}


def main() -> None:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    params = _load_params()
    gate, floor, k = params["gate"], params["assist_floor"], params["retrieval_k"]
    print(f"params: gate={gate} assist_floor={floor} retrieval_k={k}")

    test = json.loads((config.DATA_DIR / "test.json").read_text())
    if limit:
        test = test[:limit]
    print(f"TEST tickets: {len(test)}")

    llm = LLMClient()
    log = CallLog()
    out = _init_out(test, params, limit)

    # --- LLM baselines across the sweep (resumable per ticket) ---
    for n in config.TOOL_COUNTS:
        cell = out["by_tool_count"].setdefault(str(n), {"baseline_full": [], "baseline_retrieval": []})
        done_full = {d["ticket_id"] for d in cell["baseline_full"]}
        done_retr = {d["ticket_id"] for d in cell["baseline_retrieval"]}
        if len(done_full) >= len(test) and len(done_retr) >= len(test):
            print(f"n={n}: already complete, skipping")
            continue
        tools = build_tools(n)
        index = ToolIndex(tools)
        for i, t in enumerate(test):
            if t["id"] not in done_full:
                df = resolve_baseline_full(llm, t, tools)
                _log_decision(log, df); cell["baseline_full"].append(dataclasses.asdict(df)); _save(out)
            if t["id"] not in done_retr:
                dr = resolve_baseline_retrieval(llm, t, index, k)
                _log_decision(log, dr); cell["baseline_retrieval"].append(dataclasses.asdict(dr)); _save(out)
            if (i + 1) % 10 == 0:
                print(f"  n={n}: {i+1}/{len(test)}  (cost ${_running_cost(out):.4f})")
        print(f"n={n}: done. running cost ${_running_cost(out):.4f}")

    # --- Aito once on TEST (resumable) ---
    done_aito = {d["ticket_id"] for d in out["aito"]}
    if len(done_aito) < len(test):
        with AitoPredictor() as pred:
            for i, t in enumerate(test):
                if t["id"] in done_aito:
                    continue
                d = resolve_aito(pred, llm, t, gate=gate, assist_floor=floor)
                _log_decision(log, d); out["aito"].append(dataclasses.asdict(d)); _save(out)
                if (i + 1) % 10 == 0:
                    print(f"  aito: {i+1}/{len(test)}")
    else:
        print("aito: already complete, skipping")

    log.close()
    _save(out)
    print(f"\nlogged {log.n} new calls this run to {config.CALLS_LOG.relative_to(config.PKG_ROOT)}")
    print(f"total measured cost: ${_running_cost(out):.4f}")
    print(f"wrote {DECISIONS_PATH.relative_to(config.PKG_ROOT)}")


if __name__ == "__main__":
    main()
