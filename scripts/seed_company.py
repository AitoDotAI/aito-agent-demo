"""Seed the 'Northwind Cloud' company dataset into Aito.

A fictional B2B SaaS company's own numbers — so the Company AI agent can answer
predictive/diagnostic questions a SQL+LLM BI bot can't: which accounts churn and
WHY, what drives NPS down, expected MRR for a cohort, which feedback themes to fix.

Two tables, both heavy on DISCRETE features with statistical mass (per the house
style) so Aito's probabilities are reliable. Only `mrr_eur` is continuous (what
_estimate predicts).

    uv run python scripts/seed_company.py
"""

from __future__ import annotations

import random

import httpx

from src.config import load_config

SEED = 0xC0FFEE
N_ACCOUNTS = 2400
N_FEEDBACK = 3600

# ── accounts vocab (all discrete) ──────────────────────────────────
INDUSTRY = ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"]
SIZE = ["SMB", "Mid-market", "Enterprise"]
PLAN = ["Free", "Starter", "Pro", "Enterprise"]
REGION = ["Helsinki", "Stockholm", "Berlin", "London", "Remote"]
TENURE = ["<3mo", "3-12mo", "1-2y", "2y+"]
SEATS = ["1-5", "6-20", "21-100", "100+"]
ONBOARDING = ["Completed", "Partial", "None"]
SUPPORT_LOAD = ["none", "low", "high"]
USAGE = ["low", "medium", "high"]
HEALTH = ["Green", "Yellow", "Red"]
NPS_BAND = ["promoter", "passive", "detractor"]

# churn drivers (added to a base; clipped). Named so they're learnable.
_PLAN_CHURN = {"Free": 0.20, "Starter": 0.10, "Pro": -0.05, "Enterprise": -0.14}
_HEALTH_CHURN = {"Green": -0.18, "Yellow": 0.04, "Red": 0.30}
_ONB_CHURN = {"Completed": -0.12, "Partial": 0.06, "None": 0.22}
_SUP_CHURN = {"none": -0.02, "low": -0.04, "high": 0.16}
_TEN_CHURN = {"<3mo": 0.16, "3-12mo": 0.04, "1-2y": -0.05, "2y+": -0.12}
_NPS_CHURN = {"promoter": -0.16, "passive": 0.02, "detractor": 0.22}
_USE_CHURN = {"low": 0.16, "medium": 0.0, "high": -0.12}

_PLAN_MRR = {"Free": 0, "Starter": 90, "Pro": 600, "Enterprise": 2800}
_SIZE_MULT = {"SMB": 1.0, "Mid-market": 2.2, "Enterprise": 5.0}
_SEAT_MULT = {"1-5": 0.7, "6-20": 1.0, "21-100": 1.8, "100+": 3.2}


def build_accounts(rng: random.Random) -> list[dict]:
    rows = []
    ids = rng.sample(range(100000, 100000 + N_ACCOUNTS * 6), N_ACCOUNTS)
    for i in range(N_ACCOUNTS):
        ind = rng.choice(INDUSTRY)
        size = rng.choices(SIZE, weights=[5, 4, 3])[0]
        plan = rng.choices(PLAN, weights=[3, 4, 4, 2])[0]
        region = rng.choice(REGION)
        tenure = rng.choices(TENURE, weights=[3, 4, 4, 3])[0]
        seats = rng.choices(SEATS, weights=[4, 4, 3, 2])[0]
        onb = rng.choices(ONBOARDING, weights=[5, 3, 2])[0]
        sup = rng.choices(SUPPORT_LOAD, weights=[3, 5, 3])[0]
        use = rng.choices(USAGE, weights=[3, 4, 4])[0]
        health = rng.choices(HEALTH, weights=[5, 3, 2])[0]
        nps = rng.choices(NPS_BAND, weights=[4, 4, 3])[0]

        p = 0.16 + _PLAN_CHURN[plan] + _HEALTH_CHURN[health] + _ONB_CHURN[onb] \
            + _SUP_CHURN[sup] + _TEN_CHURN[tenure] + _NPS_CHURN[nps] + _USE_CHURN[use]
        p = min(0.92, max(0.02, p))
        churned = "yes" if rng.random() < p else "no"

        mrr = _PLAN_MRR[plan] * _SIZE_MULT[size] * _SEAT_MULT[seats]
        mrr = int(mrr * rng.uniform(0.8, 1.25))

        rows.append({
            "account_id": f"ACC-{ids[i]}",
            "industry": ind, "size": size, "plan": plan, "region": region,
            "tenure_band": tenure, "seats_band": seats, "onboarding": onb,
            "support_load": sup, "usage": use, "health": health, "nps_band": nps,
            "mrr_eur": mrr, "churned": churned,
        })
    return rows


# ── feedback vocab (all discrete) ──────────────────────────────────
SURVEY = ["NPS", "CSAT", "CES"]
THEME = ["Onboarding", "Support", "Pricing", "Product", "Performance", "Docs"]
CHANNEL = ["in-app", "email", "CSM"]
SCORE = ["promoter", "passive", "detractor"]

# theme → pull toward detractor(+)/promoter(-) on the score axis
_THEME_SCORE = {"Pricing": 0.26, "Support": 0.18, "Performance": 0.20,
                "Docs": 0.04, "Onboarding": -0.10, "Product": -0.18}
_PLAN_SCORE = {"Free": 0.10, "Starter": 0.04, "Pro": -0.04, "Enterprise": -0.10}


def build_feedback(rng: random.Random) -> list[dict]:
    rows = []
    ids = rng.sample(range(700000, 700000 + N_FEEDBACK * 6), N_FEEDBACK)
    for i in range(N_FEEDBACK):
        ind = rng.choice(INDUSTRY)
        size = rng.choices(SIZE, weights=[5, 4, 3])[0]
        plan = rng.choices(PLAN, weights=[3, 4, 4, 2])[0]
        region = rng.choice(REGION)
        survey = rng.choice(SURVEY)
        theme = rng.choice(THEME)
        channel = rng.choices(CHANNEL, weights=[5, 4, 2])[0]

        # probability this response is a detractor (vs promoter), from theme+plan
        d = 0.30 + _THEME_SCORE[theme] + _PLAN_SCORE[plan]
        d = min(0.9, max(0.05, d))
        r = rng.random()
        score = "detractor" if r < d else ("promoter" if r > 1 - (0.45 - (d - 0.3)) else "passive")
        # detractors more likely still unresolved; promoters n/a → mostly resolved
        resolved = "yes" if rng.random() < (0.4 if score == "detractor" else 0.8) else "no"

        rows.append({
            "feedback_id": f"FB-{ids[i]}",
            "account_industry": ind, "account_size": size, "plan": plan, "region": region,
            "survey_type": survey, "score_band": score, "theme": theme,
            "channel": channel, "resolved": resolved,
        })
    return rows


ACCOUNTS_SCHEMA = {
    "type": "table",
    "columns": {
        "account_id": {"type": "String"},
        "industry": {"type": "String"}, "size": {"type": "String"}, "plan": {"type": "String"},
        "region": {"type": "String"}, "tenure_band": {"type": "String"}, "seats_band": {"type": "String"},
        "onboarding": {"type": "String"}, "support_load": {"type": "String"}, "usage": {"type": "String"},
        "health": {"type": "String"}, "nps_band": {"type": "String"},
        "mrr_eur": {"type": "Int"}, "churned": {"type": "String"},
    },
}
FEEDBACK_SCHEMA = {
    "type": "table",
    "columns": {
        "feedback_id": {"type": "String"},
        "account_industry": {"type": "String"}, "account_size": {"type": "String"},
        "plan": {"type": "String"}, "region": {"type": "String"}, "survey_type": {"type": "String"},
        "score_band": {"type": "String"}, "theme": {"type": "String"},
        "channel": {"type": "String"}, "resolved": {"type": "String"},
    },
}


def _upload(http: httpx.Client, table: str, schema: dict, rows: list[dict]) -> None:
    sc = http.get("/api/v1/schema").json().get("schema", {})
    if table in sc:
        assert http.delete(f"/api/v1/schema/{table}").status_code < 400
    assert http.put(f"/api/v1/schema/{table}", json=schema).status_code < 400, "create failed"
    r = http.post(f"/api/v1/data/{table}/batch", json=rows)
    assert r.status_code < 400, f"upload {table} failed: {r.text[:200]}"
    cnt = http.post("/api/v1/_query", json={"from": table, "limit": 0}).json().get("total")
    assert cnt == len(rows), f"{table}: {cnt} != {len(rows)}"
    print(f"  uploaded {table}: {cnt} rows")


def main() -> None:
    rng = random.Random(SEED)
    cfg = load_config()
    acc = build_accounts(rng)
    fb = build_feedback(rng)
    print(f"accounts={len(acc)} churn-rate={sum(a['churned']=='yes' for a in acc)/len(acc):.2f}")
    print(f"feedback={len(fb)} detractor-rate={sum(f['score_band']=='detractor' for f in fb)/len(fb):.2f}")
    with httpx.Client(base_url=cfg.aito_url, headers={"x-api-key": cfg.aito_key, "content-type": "application/json"}, timeout=60.0) as http:
        _upload(http, "accounts", ACCOUNTS_SCHEMA, acc)
        _upload(http, "feedback", FEEDBACK_SCHEMA, fb)
    print("done.")


if __name__ == "__main__":
    main()
