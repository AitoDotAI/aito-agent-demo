"""Read-only v2 acceptance checks; no LLM calls, data writes, or deployment.

Unlike v2-parity, this checks meaning rather than identical probabilities.
Engine deltas still need review using the parity report before cutover.
"""

from __future__ import annotations

import json
import math
from contextlib import closing
from dataclasses import replace

from scripts.v2_parity import ROUTES
from scripts.v2_relate_check import check as check_relate, v2_config
from scripts.v2_retrieval_check import check as check_retrieval
from src.aito_client import AitoClient


def route_errors(path: str, status: int, body: dict) -> list[str]:
    if status != 200:
        return [f"HTTP {status}, expected 200"]
    errors = []
    if not isinstance(body, dict):
        return ["expected a JSON object"]
    if path == "/api/health" and not body.get("aito_connected"):
        errors.append("Aito is disconnected")
    if path.startswith("/api/resolve?"):
        gold = "repair_help" if "broadband" in path else "refund"
        if body.get("intent") != gold:
            errors.append(f"intent {body.get('intent')!r}, expected {gold}")
        if not body.get("intent_alts"):
            errors.append("missing intent alternatives")
    if path == "/api/handoff":
        counts = body.get("counts", {})
        if not body.get("total") or sum(counts.values()) != body["total"]:
            errors.append("handoff counts do not cover the sample")
        handed_off = {r.get("intent") for r in body.get("handoff", [])}
        if not {"refund", "cancel_service"} <= handed_off:
            errors.append("sensitive sample actions must require handoff")
    if path.startswith("/api/opportunity"):
        if not isinstance(body.get("effort_days"), (int, float)) or body["effort_days"] <= 0:
            errors.append("effort must be positive")
        # The Manufacturing/Analytics case deliberately has no references: it
        # checks the old zero-row-conjunct crash, not nearest-neighbour coverage.
        if path == "/api/opportunity" and not body.get("references"):
            errors.append("missing reference engagements")
    if path.startswith("/api/company-360"):
        if not body.get("kpis"):
            errors.append("missing KPI cards")
        for kpi in body.get("kpis", []):
            if not kpi.get("levers", {}).get("items"):
                errors.append(f"{kpi.get('key')}: missing recommended levers")
    # Check probabilities wherever rendered. Do not apply this to lifts/scores.
    probability_keys = {"p", "$p", "confidence", "intent_p", "param_p",
                        "base_p", "p_with", "p_without", "meeting_p"}

    def visit(value, location=""):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in probability_keys and not (
                    isinstance(child, (int, float)) and not isinstance(child, bool)
                    and math.isfinite(child) and 0 <= child <= 1):
                    errors.append(f"{location}/{key}: invalid probability {child!r}")
                visit(child, f"{location}/{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{location}[{i}]")

    visit(body)
    return errors


def main() -> int:
    cfg = v2_config()
    failures = []

    def report(label, errors):
        print(f"{'FAIL' if errors else 'PASS'} {label}", flush=True)
        for error in errors:
            print(f"  {error}", flush=True)
        failures.extend(f"{label}: {error}" for error in errors)

    with closing(AitoClient(cfg)) as client:
        master_cfg = replace(cfg, aito_url=cfg.aito_url.removesuffix("/env/v2"), aito_env=None)
        with closing(AitoClient(master_cfg)) as master:
            try:
                tables = client.get_schema().get("schema", {})
                master_tables = master.get_schema().get("schema", {})
                report("table set", [] if tables and set(tables) == set(master_tables)
                       else ["empty or different table sets"])
                for table in tables:
                    meta = client._request("GET", client._path(f"schema/{table}?meta"))
                    a = master.query(table, limit=0)["total"]
                    b = client.query(table, limit=0)["total"]
                    errors = []
                    if meta.get("engine") != "v2":
                        errors.append(f"engine is {meta.get('engine')!r}, expected v2")
                    if a != b:
                        errors.append(f"master has {a} rows, v2 has {b}")
                    report(f"table {table}", errors)
            except Exception as exc:
                report("table readiness", [str(exc)])
        try:
            result = check_relate(client)
            report("scoped _relate labels/counts/rates", result["errors"])
        except Exception as exc:
            report("scoped _relate", [str(exc)])
        try:
            result = check_retrieval(client)
            report("retrieval with unseen probe token", result["errors"])
        except Exception as exc:
            report("retrieval", [str(exc)])

        # Explicitly inject the v2 client. This cannot accidentally compare v1
        # with itself because a developer's .env pins AITO_API_VERSION=v1.
        from src import app as demo
        from fastapi.testclient import TestClient
        original_client, original_config = demo.aito, demo.config
        demo.aito, demo.config = client, cfg
        try:
            with TestClient(demo.app) as http:
                for path in ROUTES:
                    try:
                        response = http.get(path)
                        report(path, route_errors(path, response.status_code, response.json()))
                    except Exception as exc:
                        report(path, [str(exc)])
        finally:
            demo.aito, demo.config = original_client, original_config
            original_client.close()
    print(json.dumps({"failures": len(failures), "cutover_checks_pass": not failures}))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
