"""Seed the 'Northlight Consulting' sales-assistant datasets into Aito.

Two predictive intuitions from the firm's own history:
  - engagements (past projects): predict `outcome`, _estimate `effort_days`, _match references
  - outreach (cold touches):     _relate what works, _predict/_recommend reply & meeting

Design notes (per Antti): use plenty of DISCRETE features and enough rows that
every feature value — and the common pairwise combos — has statistical mass, so
Aito's probabilistic predictions are reliable. Numbers are banded into categories;
the only continuous target is `effort_days` (what _estimate predicts).

    uv run python scripts/seed_sales.py
"""

from __future__ import annotations

import random

import httpx

from src.config import load_config

SEED = 0x5A1E5
N_ENG = 1800
N_OUT = 2200

# ── engagements vocab (all discrete) ───────────────────────────────
INDUSTRY = ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"]
CLIENT_SIZE = ["SMB", "Mid-market", "Enterprise"]
SERVICE = ["Advisory", "Analytics & ML", "Integration", "Data Platform", "Cloud Migration", "Custom Dev"]
DEAL_BAND = ["S", "M", "L", "XL"]                     # <50k / 50-150 / 150-400 / >400k
MODEL = ["Fixed-price", "Time & materials", "Retainer"]
COMPLEXITY = ["Low", "Medium", "High"]
SENIORITY = ["junior-heavy", "balanced", "senior-heavy"]
REGION = ["Helsinki", "Stockholm", "Berlin", "London", "Remote"]
LEAD = ["Referral", "Partner", "Inbound", "Event", "Outbound"]
RELATIONSHIP = ["New logo", "Existing client"]
COMPETITIVE = ["Sole-source", "Competitive"]

# strong industry × service-line fit (raises win odds, named so it's learnable)
GOOD_FIT = {("SaaS", "Data Platform"), ("SaaS", "Analytics & ML"), ("Banking", "Integration"),
            ("Retail", "Analytics & ML"), ("Manufacturing", "Cloud Migration"), ("Telecom", "Integration"),
            ("Healthcare", "Advisory"), ("Logistics", "Data Platform")}
BAD_FIT = {("Public", "Custom Dev"), ("Banking", "Custom Dev"), ("Healthcare", "Cloud Migration")}

_NEED = {
    "Advisory": "a data strategy and target-state roadmap",
    "Analytics & ML": "a churn/propensity model and analytics workbench",
    "Integration": "an API integration layer across core systems",
    "Data Platform": "a unified data platform with real-time pipelines",
    "Cloud Migration": "a lift-and-modernise migration to the cloud",
    "Custom Dev": "a custom application built and shipped",
}
_BASE_EFFORT = {"Advisory": 22, "Analytics & ML": 60, "Integration": 75, "Data Platform": 100, "Cloud Migration": 115, "Custom Dev": 135}
_DEAL_MULT = {"S": 0.55, "M": 0.85, "L": 1.25, "XL": 1.8}
_CPX_MULT = {"Low": 0.8, "Medium": 1.0, "High": 1.35}
_SEN_MULT = {"junior-heavy": 1.2, "balanced": 1.0, "senior-heavy": 0.82}
_LEAD_WIN = {"Referral": 0.34, "Partner": 0.28, "Inbound": 0.10, "Event": -0.04, "Outbound": -0.14}


def build_engagements(rng: random.Random) -> list[dict]:
    rows = []
    ids = rng.sample(range(100000, 100000 + N_ENG * 5), N_ENG)
    for i in range(N_ENG):
        ind = rng.choice(INDUSTRY); svc = rng.choice(SERVICE)
        size = rng.choices(CLIENT_SIZE, weights=[4, 4, 3])[0]
        deal = rng.choices(DEAL_BAND, weights=[4, 5, 3, 2])[0]
        cpx = rng.choices(COMPLEXITY, weights=[3, 4, 3])[0]
        sen = rng.choice(SENIORITY); reg = rng.choice(REGION)
        lead = rng.choices(LEAD, weights=[3, 2, 3, 2, 4])[0]
        rel = rng.choices(RELATIONSHIP, weights=[6, 4])[0]
        comp = rng.choices(COMPETITIVE, weights=[4, 6])[0]
        model = rng.choice(MODEL)

        # win probability from discrete drivers
        p = 0.46 + _LEAD_WIN[lead]
        if (ind, svc) in GOOD_FIT: p += 0.14
        if (ind, svc) in BAD_FIT: p -= 0.16
        if rel == "Existing client": p += 0.12
        if comp == "Sole-source": p += 0.10
        if cpx == "High": p -= 0.07
        if deal == "XL": p -= 0.06
        p = min(0.95, max(0.05, p))
        outcome = "won" if rng.random() < p else "lost"

        # effort_days (the numeric to _estimate)
        eff = _BASE_EFFORT[svc] * _DEAL_MULT[deal] * _CPX_MULT[cpx] * _SEN_MULT[sen]
        eff = int(eff * rng.uniform(0.85, 1.15))
        dur = max(2, int(eff / rng.uniform(8, 16)))

        rows.append({
            "engagement_id": f"ENG-{ids[i]}",
            "client_industry": ind, "client_size": size, "service_line": svc,
            "deal_size_band": deal, "engagement_model": model, "complexity": cpx,
            "team_seniority": sen, "region": reg, "lead_source": lead,
            "relationship": rel, "competitive": comp,
            "brief": f"{size} {ind} client — {svc.lower()} engagement: {_NEED[svc]}.",
            "effort_days": eff, "duration_weeks": dur, "outcome": outcome,
        })
    return rows


# ── outreach vocab (all discrete) ──────────────────────────────────
ROLE = ["CTO", "Head of Data", "COO", "CEO", "Procurement"]
CHANNEL = ["Warm intro", "LinkedIn", "Cold email", "Cold call"]
ANGLE = ["Case study", "Referral intro", "Pain point", "Benchmark offer", "Event follow-up"]
PERSONALIZATION = ["High", "Medium", "Low"]
SUBJECT = ["Stat", "Question", "Name-drop", "Direct"]
DAY = ["Mon", "Tue", "Wed", "Thu", "Fri"]
TIME = ["Morning", "Midday", "Afternoon"]

_CH_REPLY = {"Warm intro": 0.40, "LinkedIn": 0.06, "Cold email": -0.04, "Cold call": -0.10}
_ANG_REPLY = {"Case study": 0.12, "Referral intro": 0.16, "Benchmark offer": 0.08, "Event follow-up": 0.05, "Pain point": -0.03}
_PER_REPLY = {"High": 0.15, "Medium": 0.04, "Low": -0.06}
_ROLE_REPLY = {"Head of Data": 0.06, "CTO": 0.01, "COO": -0.01, "CEO": -0.09, "Procurement": -0.04}
_SUBJ_REPLY = {"Name-drop": 0.05, "Stat": 0.04, "Question": 0.03, "Direct": 0.0}
_DAY_REPLY = {"Tue": 0.04, "Wed": 0.04, "Thu": 0.01, "Mon": 0.0, "Fri": -0.04}


def build_outreach(rng: random.Random) -> list[dict]:
    rows = []
    ids = rng.sample(range(500000, 500000 + N_OUT * 5), N_OUT)
    for i in range(N_OUT):
        ind = rng.choice(INDUSTRY); size = rng.choices(CLIENT_SIZE, weights=[4, 4, 3])[0]
        role = rng.choice(ROLE); ch = rng.choices(CHANNEL, weights=[2, 4, 5, 3])[0]
        ang = rng.choice(ANGLE); per = rng.choices(PERSONALIZATION, weights=[3, 4, 3])[0]
        subj = rng.choice(SUBJECT); day = rng.choice(DAY); tm = rng.choice(TIME)

        p = 0.18 + _CH_REPLY[ch] + _ANG_REPLY[ang] + _PER_REPLY[per] + _ROLE_REPLY[role] + _SUBJ_REPLY[subj] + _DAY_REPLY[day]
        p = min(0.92, max(0.02, p))
        replied = rng.random() < p
        # a meeting needs a reply, plus quality
        mp = 0.42 + (0.12 if ang in ("Case study", "Referral intro") else 0) + (0.1 if per == "High" else 0)
        meeting = replied and rng.random() < mp

        rows.append({
            "outreach_id": f"OUT-{ids[i]}",
            "target_industry": ind, "target_size": size, "target_role": role,
            "channel": ch, "angle": ang, "personalization": per, "subject_style": subj,
            "send_day": day, "send_time": tm,
            "replied": "yes" if replied else "no",
            "meeting": "yes" if meeting else "no",
        })
    return rows


ENG_SCHEMA = {
    "type": "table",
    "columns": {
        "engagement_id": {"type": "String"},
        "client_industry": {"type": "String"}, "client_size": {"type": "String"},
        "service_line": {"type": "String"}, "deal_size_band": {"type": "String"},
        "engagement_model": {"type": "String"}, "complexity": {"type": "String"},
        "team_seniority": {"type": "String"}, "region": {"type": "String"},
        "lead_source": {"type": "String"}, "relationship": {"type": "String"},
        "competitive": {"type": "String"}, "brief": {"type": "Text", "analyzer": "english"},
        "effort_days": {"type": "Int"}, "duration_weeks": {"type": "Int"},
        "outcome": {"type": "String"},
    },
}
OUT_SCHEMA = {
    "type": "table",
    "columns": {
        "outreach_id": {"type": "String"},
        "target_industry": {"type": "String"}, "target_size": {"type": "String"},
        "target_role": {"type": "String"}, "channel": {"type": "String"},
        "angle": {"type": "String"}, "personalization": {"type": "String"},
        "subject_style": {"type": "String"}, "send_day": {"type": "String"},
        "send_time": {"type": "String"}, "replied": {"type": "String"}, "meeting": {"type": "String"},
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
    eng = build_engagements(rng)
    out = build_outreach(rng)
    from collections import Counter
    print(f"engagements={len(eng)} win-rate={sum(e['outcome']=='won' for e in eng)/len(eng):.2f}")
    print(f"outreach={len(out)} reply-rate={sum(o['replied']=='yes' for o in out)/len(out):.2f} meeting-rate={sum(o['meeting']=='yes' for o in out)/len(out):.2f}")
    with httpx.Client(base_url=cfg.aito_url, headers={"x-api-key": cfg.aito_key, "content-type": "application/json"}, timeout=60.0) as http:
        _upload(http, "engagements", ENG_SCHEMA, eng)
        _upload(http, "outreach", OUT_SCHEMA, out)
    print("done.")


if __name__ == "__main__":
    main()
