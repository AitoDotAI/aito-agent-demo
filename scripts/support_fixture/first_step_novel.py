"""The first step's lift through the ticket link, split by novel vs seen wording.

record_envelope.py measured the first step before (category only) and after (plus
the ticket's text, read through the support_steps -> ticket link) on the 300
held-out tickets: 0.73 -> 0.94. A lift through `ticket.text` is exactly what
wording seen in training would inflate, so this re-runs both predictions (read-only
_predict against the `support` env) and scores them on the novel-text split fixed in
novel_text.py (committed 64a7e832, before this measurement).

    AITO_API_VERSION=v2 uv run python scripts/support_fixture/first_step_novel.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from compare_modes import mcnemar_exact, wilson  # noqa: E402
from novel_text import split  # noqa: E402
from src import app as A  # noqa: E402
from src.aito_client import AitoError  # noqa: E402
from src.support_envelope import DETOURS, guarded, load_incoming  # noqa: E402

OUT = HERE / "results" / "first_step_novel.json"


def main() -> int:
    aito = A._support_client()
    q = load_incoming()
    novel, seen = split()
    rows = []
    for tid in q["order"]:
        t, steps = q["tickets"][tid], q["steps"].get(tid, [])
        real = [s["action"] for s in steps if s["action"] not in DETOURS]
        if not real:
            continue
        base = {"previous_action": "start", "category": t["category"]}
        try:
            before = guarded(aito, "support_steps", base, "action")["value"]
            after = guarded(aito, "support_steps", {**base, "ticket.text": t["text"]}, "action")["value"]
        except AitoError as e:
            rows.append({"ticket_id": tid, "error": str(e)})
            continue
        rows.append({"ticket_id": tid, "truth": real[0], "before": before, "after": after,
                     "group": "novel_text" if tid in novel else "seen_text"})
    out = {"what": "first step, category only (before) vs plus the ticket's text through the link (after), "
                   "with the TRUE category as input, re-run read-only; split from novel_text.py",
           "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "engine": aito._request("GET", aito._path("_version")),
           "errors": sum("error" in r for r in rows), "groups": {}}
    ok = [r for r in rows if "error" not in r]
    for name in ("novel_text", "seen_text", "all"):
        rs = [r for r in ok if name == "all" or r["group"] == name]
        b = [r["before"] == r["truth"] for r in rs]
        a = [r["after"] == r["truth"] for r in rs]
        only_b = sum(x and not y for x, y in zip(b, a))
        only_a = sum(y and not x for x, y in zip(b, a))
        out["groups"][name] = {"n": len(rs), "before": round(sum(b) / len(rs), 3), "before_ci95": wilson(sum(b), len(rs)),
                               "after": round(sum(a) / len(rs), 3), "after_ci95": wilson(sum(a), len(rs)),
                               "only_before_right": only_b, "only_after_right": only_a,
                               "mcnemar_p": mcnemar_exact(only_b, only_a)}
    out["rows"] = rows
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for name, g in out["groups"].items():
        print(f"{name}: n={g['n']} before {g['before']} after {g['after']} (p {g['mcnemar_p']})")
    print("errors:", out["errors"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
