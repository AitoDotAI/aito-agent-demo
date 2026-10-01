"""Re-score the recorded support benchmark on the held-out tickets whose wording is new.

The 300 held-out tickets were never loaded into Aito, but the fixture is written
from templates, so 166 of them share their exact text with a loaded ticket. This
re-scores every recorded arm on the other 134, and on the 166 for comparison.
No model or Aito call is made: it reads the recorded answers in results/.

The split was fixed before any arm but Aito's was scored on it (the audit of
2026-09-30 had computed Aito's figures): a held-out ticket is "novel" when its text,
lowercased and whitespace-normalised, matches no text in the loaded training data
(data/support_tickets.json). Scoring is compare_modes.py's own: a ticket counts as
"all five right" when every decision with a recorded truth is right, and the
arms are paired against Aito only with McNemar's exact test.

    uv run python scripts/support_fixture/novel_text.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from compare_modes import LOG, RAG_LOG, TARGETS, WHY_LOG, mcnemar_exact, wilson  # noqa: E402

TRAIN = HERE / "data" / "support_tickets.json"
INCOMING = HERE.parent.parent / "src" / "data" / "support_incoming.json"
OUT = HERE / "results" / "novel_text.json"


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def split() -> tuple[set[str], set[str]]:
    """(novel, seen) held-out ticket ids."""
    seen_texts = Counter(norm(t["text"]) for t in json.loads(TRAIN.read_text()))
    held = json.loads(INCOMING.read_text())["tickets"]
    novel = {t["ticket_id"] for t in held if not seen_texts[norm(t["text"])]}
    return novel, {t["ticket_id"] for t in held} - novel


def main() -> int:
    rows = {r["ticket_id"]: r for r in (json.loads(x) for x in LOG.read_text().splitlines())}
    for path, key in ((RAG_LOG, "rag"), (WHY_LOG, "why")):
        for r in (json.loads(x) for x in path.read_text().splitlines()):
            rows[r["ticket_id"]][key] = r
    arms = {"aito_only": lambda r: r["aito"], "aito_plus_llm": lambda r: r["coop"]["values"],
            "llm_only": lambda r: r["llm_only"]["values"], "rag_llm": lambda r: r["rag"]["values"],
            "aito_shortlist_why_llm": lambda r: r["why"]["values"]}

    def ok(get, r):
        return all(get(r)[k] == r["truth"][k] for k in TARGETS if r["truth"][k] is not None)

    novel, seen = split()
    out = {"what": "the recorded support benchmark (compare_modes) re-scored by whether a held-out ticket's wording "
                   "also occurs in the loaded training data; no new model or Aito calls",
           "caveat": "synthetic fixture with planted effects; gpt-5-mini; the novel split's Aito figures were seen in "
                     "the 2026-09-30 audit before this script fixed the split",
           "groups": {}}
    for name, ids in (("novel_text", novel), ("seen_text", seen), ("all", novel | seen)):
        rs = [rows[i] for i in sorted(ids)]
        g = {"n": len(rs), "arms": {}, "paired_vs_aito_only": {}}
        for arm, get in arms.items():
            k = sum(ok(get, r) for r in rs)
            per = {}
            for t in TARGETS:
                pairs = [(get(r)[t], r["truth"][t]) for r in rs if r["truth"][t] is not None]
                per[t] = round(sum(a == b for a, b in pairs) / len(pairs), 3)
            g["arms"][arm] = {"all_five_right": round(k / len(rs), 3), "ci95": wilson(k, len(rs)), "per_decision": per}
            if arm != "aito_only":
                b = sum(ok(arms["aito_only"], r) and not ok(get, r) for r in rs)
                c = sum(ok(get, r) and not ok(arms["aito_only"], r) for r in rs)
                g["paired_vs_aito_only"][arm] = {"only_aito_right": b, "only_other_right": c, "mcnemar_p": mcnemar_exact(b, c)}
        out["groups"][name] = g
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for name, g in out["groups"].items():
        print(f"{name} (n={g['n']}): " + ", ".join(f"{a} {v['all_five_right']:.3f}" for a, v in g["arms"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
