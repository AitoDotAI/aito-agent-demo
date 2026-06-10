"""Seed the tool-routing demo's history into Aito's `tool_calls` table.

The /api/route "short-list" view (Tool routing · short-list) predicts which of the
240 catalog tools applies to a ticket — it learns from historical (text -> tool)
calls. This regenerates that history from the telco-tool-routing-bench generator
and uploads it.

IMPORTANT: this lives in its own table `tool_calls`, NOT `tickets` — the company
360 demo (seed_company.py) owns a `tickets` table (CSAT data), and the two must
not collide (they did once, which 400'd /api/route).

    uv run python scripts/seed_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from src.config import load_config

# the bench's data generators are pure-Python; reuse them rather than duplicate
_BENCH = Path(__file__).resolve().parent.parent / "telco-tool-routing-bench"
sys.path.insert(0, str(_BENCH))
from data.tickets import build_tickets  # noqa: E402

TABLE = "tool_calls"
SCHEMA = {
    "type": "table",
    "columns": {
        "ticket_id": {"type": "String"},
        "text": {"type": "Text", "analyzer": "english"},
        # nullable: ambiguous tickets have no single correct tool — their null
        # label makes _predict return low, spread $p so the gate escalates.
        "tool": {"type": "String", "nullable": True},
        "escalation_target": {"type": "String", "nullable": True},
    },
}


def main() -> None:
    cfg = load_config()
    tickets = build_tickets()
    rows = [{"ticket_id": t["id"], "text": t["text"], "tool": t["correct_tool"],
             "escalation_target": t["escalation_target"]} for t in tickets]
    print(f"{TABLE}: {len(rows)} rows · with-tool={sum(1 for r in rows if r['tool'])} · "
          f"escalations={sum(1 for r in rows if r['tool'] is None)}")
    with httpx.Client(base_url=cfg.aito_url, headers={"x-api-key": cfg.aito_key, "content-type": "application/json"}, timeout=60.0) as http:
        sc = http.get("/api/v1/schema").json().get("schema", {})
        if TABLE in sc:
            assert http.delete(f"/api/v1/schema/{TABLE}").status_code < 400
        assert http.put(f"/api/v1/schema/{TABLE}", json=SCHEMA).status_code < 400, "create failed"
        r = http.post(f"/api/v1/data/{TABLE}/batch", json=rows)
        assert r.status_code < 400, f"upload failed: {r.text[:200]}"
        cnt = http.post("/api/v1/_query", json={"from": TABLE, "limit": 0}).json().get("total")
        assert cnt == len(rows), f"{cnt} != {len(rows)}"
        print(f"  uploaded {TABLE}: {cnt} rows")
    print("done.")


if __name__ == "__main__":
    main()
