"""Read-only repro: scoped _relate statistics must describe the labelled driver.

    python -m scripts.v2_relate_check

Uses the demo's existing env/v2 branch. Never migrates or writes data.
Exact frequencies are independently checked with _query; v2 ps uses raw counts.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from contextlib import closing

from src.aito_client import AitoClient
from src.config import load_config


def v2_config(env: str = "v2"):
    cfg = load_config()
    root = cfg.aito_url
    if cfg.aito_env:
        root = root.removesuffix(f"/env/{cfg.aito_env}")
    return replace(cfg, aito_url=f"{root}/env/{env}" if env else root,
                   aito_api_version="v2", aito_env=env or None)


def check_rates(hit: dict, *, population: int, outcome: int, driver: int,
                both: int) -> list[str]:
    """Assert both the raw-cell orientation and probabilities, not just range."""
    expected_fs = {"n": population, "f": outcome, "fCondition": driver,
                   "fOnCondition": both, "fOnNotCondition": outcome - both}
    expected_ps = {
        "p": outcome / population if population else None,
        "pCondition": driver / population if population else None,
        "pOnCondition": both / driver if driver else None,
        "pOnNotCondition": (outcome - both) / (population - driver)
        if population > driver else None,
    }
    errors = []
    for block, expected in (("fs", expected_fs), ("ps", expected_ps)):
        for key, want in expected.items():
            got = (hit.get(block) or {}).get(key)
            valid = got is None if want is None else (
                isinstance(got, (int, float)) and not isinstance(got, bool)
                and math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9))
            if not valid or key not in (hit.get(block) or {}):
                errors.append(f"{block}.{key}: got {got!r}, expected {want!r}")
    return errors


def check(client: AitoClient) -> dict:
    population = {"customer.size": "SMB"}
    outcome = {"converted": "no"}
    driver = {"source": "Outbound"}

    def count(where):
        return client.query("deals", where, limit=0)["total"]

    counts = {
        "population": count(population),
        "outcome": count({**population, **outcome}),
        "driver": count({**population, **driver}),
        "both": count({**population, **outcome, **driver}),
    }
    hits = client.relate_on("deals", outcome, population).get("hits", [])
    hit = next((h for h in hits if h.get("condition") in (
        driver, {"source": {"$has": "Outbound"}})), None)
    if hit is None:
        errors = ["missing Outbound driver in scoped _relate"]
    elif not (0 < counts["driver"] < counts["population"]):
        errors = ["fixture must include both Outbound and other SMB deals"]
    else:
        errors = check_rates(hit, **counts)
    return {"case": "SMB outbound lost deals", "counts": counts,
            "hit": hit, "errors": errors}


def main() -> int:
    try:
        with closing(AitoClient(v2_config())) as client:
            result = check(client)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
