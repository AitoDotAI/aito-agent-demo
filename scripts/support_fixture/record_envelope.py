"""Record the support envelope over the whole held-out queue, against live Aito.

Runs src/support_envelope.envelope() for every one of the 300 incoming tickets
(never loaded into Aito) against the `support` environment, and writes
results/support_envelope_run.json: per-step accuracy against what happened, the
$p gate split and how right each tier was, how well the risk steps rank, and
latency. This file is the source for any number the envelope page claims.

    AITO_API_VERSION=v2 uv run python scripts/support_fixture/record_envelope.py
"""

from __future__ import annotations

import json
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from src import app as A  # noqa: E402
from src.support_envelope import envelope, load_incoming  # noqa: E402

OUT = ROOT / "scripts" / "support_fixture" / "results" / "support_envelope_run.json"


def auc(pos: list[float], neg: list[float]) -> float | None:
    """P(a random positive scores above a random negative); 0.5 = no ranking."""
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def main() -> None:
    aito = A._support_client()
    q = load_incoming()
    per_step: dict[str, list[bool]] = defaultdict(list)
    gates: dict[str, list[bool]] = defaultdict(list)
    risk_det, risk_other, ups_yes, ups_no, total_ms, wall = [], [], [], [], [], []
    for tid in q["order"]:
        t = q["tickets"][tid]
        t0 = time.perf_counter()
        out = envelope(aito, t, q["steps"].get(tid, []))
        wall.append((time.perf_counter() - t0) * 1000)
        total_ms.append(out["aito_ms"])
        for s in out["steps"]:
            if s.get("correct") is not None:
                per_step[s["key"]].append(bool(s["correct"]))
            if s["key"] == "resolution":
                gates[s["gate"]].append(bool(s["correct"]))
            if s["key"] == "risk" and s["risk"]["p"] is not None:
                (risk_det if t["nps_after"] == "detractor" else risk_other).append(s["risk"]["p"])
            if s["key"] == "upsell" and t["upsell_offered"] == "yes" and s["risk"]["p"] is not None:
                (ups_yes if t["upsell_accepted"] == "yes" else ups_no).append(s["risk"]["p"])
    n = len(q["order"])
    result = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": aito._request("GET", aito._path("_version")),
        "env": A._SUPPORT_ENV, "tickets": n,
        "decisions": {k: {"n": len(v), "right": sum(v), "share": round(sum(v) / len(v), 3)} for k, v in per_step.items()},
        "resolution_gate": {g: {"n": len(v), "share_of_queue": round(len(v) / n, 3),
                                "right": round(sum(v) / len(v), 3) if v else None} for g, v in gates.items()},
        "risk_detractor": {"auc": auc(risk_det, risk_other), "mean_p_detractors": round(st.mean(risk_det), 3) if risk_det else None,
                           "mean_p_others": round(st.mean(risk_other), 3) if risk_other else None,
                           "n_detractors": len(risk_det), "n_others": len(risk_other)},
        "risk_upsell": {"auc": auc(ups_yes, ups_no), "n_accepted": len(ups_yes), "n_declined": len(ups_no)},
        "latency_ms": {"aito_p50": round(st.median(total_ms)), "aito_p95": round(sorted(total_ms)[int(0.95 * n) - 1]),
                       "wall_p50": round(st.median(wall)), "calls_per_ticket": 11},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "engine"}, indent=1))


if __name__ == "__main__":
    main()
