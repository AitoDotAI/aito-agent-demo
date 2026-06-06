"""Choose gate, assist_floor and retrieval-k on the VAL split ONLY.

TEST is never read here. Results are written to results/chosen_params.json and
consumed by the runner. The VAL predictions are cached to results/val_cache.json
so re-running is cheap and the chosen params are stable.

Rules (no tuning on test, no hand-rolled calibration):
  - retrieval_k: smallest k whose VAL retrieval recall (gold tool in top-k) on
    clear/medium tickets reaches K_TARGET. This is the shortlist-depth decision a
    retrieval engineer actually makes.
  - gate: smallest threshold whose auto-fire accuracy on VAL reaches GATE_TARGET,
    so the gate only fires when Aito's confident calls are empirically reliable.
  - assist_floor: the floor that maximizes VAL handled-correct given that gate,
    tie-broken toward fewer LLM calls.
"""

from __future__ import annotations

import json

from aito.predict import AitoPredictor
from bench import config
from bench.llm import LLMClient
from bench.llm_agent import ToolIndex
from data.tools import ANSWER_TOOLS, build_tools

GATE_TARGET = 0.95          # required auto-fire accuracy on VAL
K_TARGET = 0.95             # required retrieval recall on VAL (clear/medium)
K_GRID = [4, 6, 8, 12, 16, 24, 32]
_TOOL_BY_NAME = {t["name"]: t for t in ANSWER_TOOLS}


def _val() -> list[dict]:
    return json.loads((config.DATA_DIR / "val.json").read_text())


# --- retrieval k -----------------------------------------------------------
def choose_k(val: list[dict]) -> tuple[int, dict]:
    # k is independent of N: the answer tools are present at every catalog size,
    # so we measure recall against the full catalog (hardest case).
    index = ToolIndex(build_tools(max(config.TOOL_COUNTS)))
    answerable = [t for t in val if t["correct_tool"]]
    recall_by_k = {}
    for k in K_GRID:
        hits = 0
        for t in answerable:
            names = {tt["name"] for tt in index.topk(t["text"], k)}
            hits += t["correct_tool"] in names
        recall_by_k[k] = hits / len(answerable)
    chosen = next((k for k in K_GRID if recall_by_k[k] >= K_TARGET), K_GRID[-1])
    return chosen, {"recall_by_k": recall_by_k, "target": K_TARGET, "n_answerable": len(answerable)}


# --- Aito gate + assist floor ----------------------------------------------
def _build_val_cache(val: list[dict]) -> list[dict]:
    """Run each VAL ticket through Aito (tool + escalation predict) and the assist
    LLM once; cache everything so threshold sweeps need no further calls.

    Resumable: rows are checkpointed to disk after each ticket, so a rate-limit
    crash mid-run is recovered by simply re-running (completed ids are skipped)."""
    cache_path = config.RESULTS_DIR / "val_cache.json"
    rows: list[dict] = json.loads(cache_path.read_text()) if cache_path.exists() else []
    done = {r["id"] for r in rows}
    if len(done) >= len(val):
        return rows
    llm = LLMClient()
    with AitoPredictor() as pred:
        for t in val:
            if t["id"] in done:
                continue
            tp = pred.predict_tool(t["text"])
            top4 = [c.feature for c in tp.candidates if c.feature]
            shortlist = [_TOOL_BY_NAME[n] for n in top4 if n in _TOOL_BY_NAME]
            assist_pick = llm.select_tool(t["text"], shortlist).tool if shortlist else None
            ep = pred.predict_escalation(t["text"])
            rows.append({
                "id": t["id"], "difficulty": t["difficulty"],
                "correct_tool": t["correct_tool"], "is_escalation": t["is_escalation"],
                "escalation_target": t["escalation_target"],
                "p": tp.top.p, "top_feature": tp.top.feature, "top4": top4,
                "assist_pick": assist_pick, "esc_desk": ep.top.feature,
            })
            cache_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False))  # checkpoint
    return rows


def _handled(row: dict, gate: float, floor: float) -> bool:
    p = row["p"]
    if p >= gate:
        return (not row["is_escalation"]) and row["top_feature"] == row["correct_tool"]
    if p >= floor:
        return (not row["is_escalation"]) and row["assist_pick"] == row["correct_tool"]
    return bool(row["is_escalation"]) and row["esc_desk"] == row["escalation_target"]


def choose_gate_and_floor(cache: list[dict]) -> tuple[float, float, dict]:
    grid = [round(x / 100, 2) for x in range(50, 100, 2)]  # 0.50 .. 0.98
    # gate: smallest g whose auto-fire accuracy >= GATE_TARGET
    gate = None
    gate_diag = {}
    for g in grid:
        fired = [r for r in cache if r["p"] >= g]
        if not fired:
            continue
        acc = sum(1 for r in fired if (not r["is_escalation"]) and r["top_feature"] == r["correct_tool"]) / len(fired)
        gate_diag[g] = {"n_fired": len(fired), "acc": round(acc, 4)}
        if acc >= GATE_TARGET and gate is None:
            gate = g
    if gate is None:  # nothing reached target — use the most accurate non-empty gate
        gate = max(gate_diag, key=lambda g: (gate_diag[g]["acc"], gate_diag[g]["n_fired"]))

    # assist_floor: maximize VAL handled-correct, tie-break toward fewer LLM calls
    best = None
    for f in [x for x in grid if x <= gate]:
        handled = sum(1 for r in cache if _handled(r, gate, f))
        llm_calls = sum(1 for r in cache if f <= r["p"] < gate)
        key = (handled, -llm_calls)
        if best is None or key > best[0]:
            best = (key, f, handled, llm_calls)
    _, floor, handled, llm_calls = best
    diag = {
        "gate_grid": gate_diag, "chosen_gate": gate, "gate_target": GATE_TARGET,
        "chosen_floor": floor, "val_handled_correct": handled, "val_total": len(cache),
        "val_assist_calls": llm_calls,
    }
    return gate, floor, diag


def main() -> None:
    val = _val()
    k, k_diag = choose_k(val)
    cache = _build_val_cache(val)
    gate, floor, gf_diag = choose_gate_and_floor(cache)
    params = {
        "retrieval_k": k,
        "gate": gate,
        "assist_floor": floor,
        "val_diagnostics": {"k": k_diag, "gate_floor": gf_diag},
    }
    config.CHOSEN_PARAMS.write_text(json.dumps(params, indent=2, ensure_ascii=False))
    print("chosen on VAL:")
    print(f"  retrieval_k   = {k}  (recall {k_diag['recall_by_k'].get(k)})")
    print(f"  gate          = {gate}  (auto-fire acc target {GATE_TARGET})")
    print(f"  assist_floor  = {floor}")
    print(f"  VAL handled   = {gf_diag['val_handled_correct']}/{gf_diag['val_total']}")
    print(f"  wrote {config.CHOSEN_PARAMS.relative_to(config.PKG_ROOT)}")


if __name__ == "__main__":
    main()
