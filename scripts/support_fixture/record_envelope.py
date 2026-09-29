"""Record the support envelope over the whole held-out queue, against live Aito.

Runs src/support_envelope.envelope() for every one of the 300 incoming tickets
(never loaded into Aito) against the `support` environment, and writes
results/support_envelope_run.json. That file is the source for any number the
envelope page claims, and every number is on a synthetic fixture with planted
effects (scripts/support_fixture/README.md).

It records:
- per-step accuracy against what happened, with 95% Wilson intervals;
- the $p gate split, and how right each tier was;
- how well the risk steps rank (AUC);
- the first step before (category only) and after (plus the ticket's text);
- latency sequential vs parallel, interleaved per ticket from the same client, so
  both see the same load;
- a CONTROL: the ticket texts shuffled across tickets (everything else kept). The
  text-driven steps must fall toward their base rate, or the text is not what
  is doing the work.

    AITO_API_VERSION=v2 uv run python scripts/support_fixture/record_envelope.py
"""

from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from src import app as A  # noqa: E402
from src.support_envelope import DETOURS, envelope, guarded, load_incoming  # noqa: E402

OUT = ROOT / "scripts" / "support_fixture" / "results" / "support_envelope_run.json"
CAVEAT = "on a synthetic fixture with planted effects (scripts/support_fixture/README.md)"


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def share(flags: list[bool]) -> dict:
    k, n = sum(flags), len(flags)
    return {"n": n, "right": k, "share": round(k / n, 3) if n else None, "ci95": wilson(k, n)}


def auc(pos: list[float], neg: list[float]) -> float | None:
    """P(a random positive scores above a random negative); 0.5 = no ranking."""
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def pct(xs: list[float], q: float) -> int:
    s = sorted(xs)
    return round(s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))])


def chance_rates(q: dict) -> dict:
    """What a permuted input scores by chance: the sum of squared class shares (a
    shuffled ticket's prediction lands on class c about as often as c occurs)."""
    out = {}
    for key, values in (("category", [q["tickets"][t]["category"] for t in q["order"]]),
                        ("resolution", [q["tickets"][t]["resolution"] for t in q["order"]]),
                        ("first_step", [next((s["action"] for s in q["steps"].get(t, []) if s["action"] not in DETOURS),
                                             None) for t in q["order"]])):
        c = Counter(v for v in values if v is not None)
        n = sum(c.values())
        out[key] = round(sum((k / n) ** 2 for k in c.values()), 3)
    return out


def main() -> None:
    aito = A._support_client()
    q = load_incoming()
    order = q["order"]
    per_step: dict[str, list[bool]] = defaultdict(list)
    gates: dict[str, list[bool]] = defaultdict(list)
    first_before: list[bool] = []
    risk_det, risk_other, ups_yes, ups_no = [], [], [], []
    wall_seq, wall_par = [], []
    for i, tid in enumerate(order):
        t, true_steps = q["tickets"][tid], q["steps"].get(tid, [])
        # interleave which mode goes first, so neither always gets the warmer cache
        runs = [("par", True), ("seq", False)] if i % 2 else [("seq", False), ("par", True)]
        for mode, parallel in runs:
            out = envelope(aito, t, true_steps, parallel=parallel)
            (wall_par if parallel else wall_seq).append(out["wall_ms"])
            if parallel:
                res = out
        for s in res["steps"]:
            if s.get("correct") is not None:
                per_step[s["key"]].append(bool(s["correct"]))
            if s["key"] == "resolution":
                gates[s["gate"]].append(bool(s["correct"]))
            if s["key"] == "risk" and s["risk"]["p"] is not None:
                (risk_det if t["nps_after"] == "detractor" else risk_other).append(s["risk"]["p"])
            if s["key"] == "upsell" and t["upsell_offered"] == "yes" and s["risk"]["p"] is not None:
                (ups_yes if t["upsell_accepted"] == "yes" else ups_no).append(s["risk"]["p"])
        # the first step as it was before: from the predicted category alone
        cat = next(s["value"] for s in res["steps"] if s["key"] == "category")
        real = [s["action"] for s in true_steps if s["action"] not in DETOURS]
        if real:
            before = guarded(aito, "support_steps", {"previous_action": "start",
                                                     **({"category": cat} if cat else {})}, "action")
            first_before.append(before["value"] == real[0])

    # CONTROL: shuffle the text across tickets, keep every other field
    rng = random.Random(1512)
    texts = [q["tickets"][tid]["text"] for tid in order]
    rng.shuffle(texts)
    control: dict[str, list[bool]] = defaultdict(list)
    for tid, text in zip(order, texts):
        t = {**q["tickets"][tid], "text": text}
        out = envelope(aito, t, q["steps"].get(tid, []))
        for s in out["steps"]:
            if s["key"] in ("category", "resolution", "first_step", "product") and s.get("correct") is not None:
                control[s["key"]].append(bool(s["correct"]))
    majority = {}
    for key, field in (("category", "category"), ("resolution", "resolution")):
        c = Counter(q["tickets"][tid][field] for tid in order)
        majority[key] = round(c.most_common(1)[0][1] / len(order), 3)
    firsts = Counter(next((s["action"] for s in q["steps"].get(tid, []) if s["action"] not in DETOURS), None)
                     for tid in order)
    firsts.pop(None, None)
    majority["first_step"] = round(firsts.most_common(1)[0][1] / sum(firsts.values()), 3)

    n = len(order)
    result = {
        "caveat": CAVEAT,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": aito._request("GET", aito._path("_version")),
        "env": A._SUPPORT_ENV, "tickets": n,
        "decisions": {k: share(v) for k, v in per_step.items()},
        "first_step_before_after": {"category_only": share(first_before), "category_and_text": share(per_step["first_step"])},
        "resolution_gate": {g: {**share(v), "share_of_queue": round(len(v) / n, 3)} for g, v in gates.items()},
        "risk_detractor": {"auc": auc(risk_det, risk_other), "n_detractors": len(risk_det), "n_others": len(risk_other),
                           "mean_p_detractors": round(st.mean(risk_det), 3) if risk_det else None,
                           "mean_p_others": round(st.mean(risk_other), 3) if risk_other else None},
        "risk_upsell": {"auc": auc(ups_yes, ups_no), "n_accepted": len(ups_yes), "n_declined": len(ups_no)},
        "latency_ms": {"calls_per_ticket": 11,
                       "sequential": {"p50": pct(wall_seq, 0.5), "p95": pct(wall_seq, 0.95)},
                       "parallel": {"p50": pct(wall_par, 0.5), "p95": pct(wall_par, 0.95)},
                       "note": "wall time per ticket from this client to shared.aito.ai, both modes interleaved per ticket"},
        "control_shuffled_text": {"what": "texts permuted across the 300 tickets (seed 1512), all other fields kept",
                                  "real": {k: per_step[k] and share(per_step[k])["share"] for k in control},
                                  "shuffled": {k: share(v) for k, v in control.items()},
                                  "chance_rate": chance_rates(q), "majority_base_rate": majority,
                                  "note": ("a shuffled text should score at chance_rate; the first step's shuffled "
                                           "score also carries the shuffled category, so the clean isolation of the "
                                           "text's effect on the first step is first_step_before_after")},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "engine"}, indent=1))


if __name__ == "__main__":
    main()
