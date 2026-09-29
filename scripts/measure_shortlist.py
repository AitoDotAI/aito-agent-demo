"""Measure the short-list claim live: the same LLM picks a tool over the whole
catalog, then over Aito's top-5, and we record the input tokens of each.

Writes telco-tool-routing-bench/results/shortlist_live.json, which is the source
for the "fewer tokens" numbers on the Overview page. It calls /api/route in-process,
so it uses whatever Aito target and LLM the environment selects; the engine version
is recorded next to the numbers.

    AITO_API_VERSION=v2 uv run python scripts/measure_shortlist.py [N]
"""

from __future__ import annotations

import json
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from src.app import aito, app

ROOT = Path(__file__).resolve().parent.parent
TEST = ROOT / "telco-tool-routing-bench" / "data" / "test.json"
OUT = ROOT / "telco-tool-routing-bench" / "results" / "shortlist_live.json"


def main(n: int) -> None:
    # The first n non-escalation TEST tickets: a fixed, reproducible sample.
    tickets = [t for t in json.loads(TEST.read_text()) if not t["is_escalation"]][:n]
    client = TestClient(app)
    rows = []
    for t in tickets:
        r = client.post("/api/route", json={"text": t["text"]})
        r.raise_for_status()
        d = r.json()
        rows.append({"id": t["id"], "gold": t["correct_tool"],
                     "full_input_tokens": d["llm_full"]["input_tokens"], "full_pick": d["llm_full"]["tool"],
                     "coop_input_tokens": d["llm_coop"]["input_tokens"], "coop_pick": d["llm_coop"]["tool"],
                     "shortlist": [s["tool"] for s in d["shortlist"]], "catalog_size": d["catalog_size"]})
    full = st.median(x["full_input_tokens"] for x in rows)
    coop = st.median(x["coop_input_tokens"] for x in rows)
    try:
        engine = aito._request("GET", aito._path("_version"))
    except Exception as e:  # noqa: BLE001 - v1 has no _version; record why
        engine = {"unavailable": str(e)}
    out = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": engine, "api_version": aito._ver, "model": d["model"], "n": len(rows),
        "median_full_input_tokens": full, "median_coop_input_tokens": coop,
        "ratio": round(full / coop, 1),
        "same_pick": sum(x["full_pick"] == x["coop_pick"] for x in rows),
        "full_correct": sum(x["full_pick"] == x["gold"] for x in rows),
        "coop_correct": sum(x["coop_pick"] == x["gold"] for x in rows),
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print({k: v for k, v in out.items() if k != "rows"})


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
