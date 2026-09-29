"""Is the envelope's $p calibrated? Measured on the 300 held-out tickets.

For each decision step: when Aito says p, is it right p of the time? Reliability
bins (equal-width), the expected calibration error (ECE: the count-weighted gap
between stated confidence and observed accuracy) and the Brier score. For the two
risk steps, the same question about the stated probability of the outcome. Writes
results/support_calibration.json; on a synthetic fixture with planted effects.

    AITO_API_VERSION=v2 uv run python scripts/support_fixture/calibration.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from src import app as A  # noqa: E402
from src.support_envelope import envelope, load_incoming  # noqa: E402

OUT = ROOT / "scripts" / "support_fixture" / "results" / "support_calibration.json"
DECISIONS = ["category", "priority", "resolution", "kb", "first_step"]


def calibration(pairs: list[tuple[float, bool]], bins: int) -> dict:
    """pairs: (stated probability, whether the outcome happened / the answer was right)."""
    buckets = defaultdict(list)
    for p, y in pairs:
        buckets[min(bins - 1, int(p * bins))].append((p, y))
    rows, ece = [], 0.0
    for b in sorted(buckets):
        xs = buckets[b]
        conf = sum(p for p, _ in xs) / len(xs)
        acc = sum(y for _, y in xs) / len(xs)
        ece += len(xs) / len(pairs) * abs(conf - acc)
        rows.append({"bin": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "n": len(xs),
                     "stated": round(conf, 3), "observed": round(acc, 3)})
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    return {"n": len(pairs), "ece": round(ece, 3), "brier": round(brier, 3),
            "mean_stated": round(sum(p for p, _ in pairs) / len(pairs), 3),
            "observed": round(sum(y for _, y in pairs) / len(pairs), 3), "bins": rows}


def main() -> None:
    aito = A._support_client()
    q = load_incoming()
    pairs: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for tid in q["order"]:
        t = q["tickets"][tid]
        out = envelope(aito, t, q["steps"].get(tid, []))
        for s in out["steps"]:
            if s["key"] in DECISIONS and s.get("correct") is not None and s.get("p") is not None:
                pairs[s["key"]].append((s["p"], bool(s["correct"])))
            if s["key"] == "risk" and s["risk"]["p"] is not None:
                pairs["risk_detractor"].append((s["risk"]["p"], t["nps_after"] == "detractor"))
            if s["key"] == "upsell" and t["upsell_offered"] == "yes" and s["risk"]["p"] is not None:
                pairs["risk_upsell"].append((s["risk"]["p"], t["upsell_accepted"] == "yes"))
    result = {
        "caveat": "on a synthetic fixture with planted effects (scripts/support_fixture/README.md); 300 held-out tickets",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": aito._request("GET", aito._path("_version")), "env": A._SUPPORT_ENV,
        "decisions": {k: calibration(pairs[k], 10) for k in DECISIONS},
        "risks": {k: calibration(pairs[k], 5) for k in ("risk_detractor", "risk_upsell")},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    for group in ("decisions", "risks"):
        for k, v in result[group].items():
            print(f"{k:15} n={v['n']:3} ECE {v['ece']:.3f} Brier {v['brier']:.3f} stated {v['mean_stated']:.3f} observed {v['observed']:.3f}")
            for b in v["bins"]:
                print(f"      {b['bin']}  n={b['n']:3}  stated {b['stated']:.2f}  observed {b['observed']:.2f}")


if __name__ == "__main__":
    main()
