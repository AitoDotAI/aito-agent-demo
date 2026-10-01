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
N_OUT = 6000  # meetings are rare (~3%), so enough rows to learn them from

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

# Reference briefs: the client (by industry, no real company names) and the work done, so the
# references shown together read as distinct past projects. Picked by each row's position in its
# (industry, service) group, so they never consume the main random stream: every other column
# of the fixture is unchanged by them.
_CLIENTS = {
    "SaaS": ["a Helsinki HR-software scale-up", "a subscription-billing vendor", "a fintech platform company",
             "a B2B marketing-automation vendor"],
    "Retail": ["a Nordic grocery chain", "a fashion e-commerce brand", "a home-improvement retailer",
               "a sporting-goods chain"],
    "Banking": ["a regional savings bank", "a payments processor", "a mortgage lender", "a consumer-credit company"],
    "Manufacturing": ["a paper-machinery maker", "an industrial pump manufacturer", "a food-processing group",
                      "a steel-components supplier"],
    "Healthcare": ["a hospital district", "a private clinic chain", "a medical-device maker", "a pharmacy chain"],
    "Public": ["a city transport authority", "a national statistics agency", "a municipal social-services unit",
               "a regional rescue service"],
    "Telecom": ["a mobile operator", "a regional fibre provider", "a cable network", "an IoT connectivity provider"],
    "Logistics": ["a parcel-delivery company", "a port operator", "a cold-chain freight carrier",
                  "a warehouse-automation integrator"],
}
_WORK = {
    "Data Platform": ["replaced a nightly batch warehouse with streaming pipelines",
                      "built a governed lakehouse for finance and operations reporting",
                      "consolidated scattered data marts into one platform",
                      "set up the shared customer data model its teams now build on",
                      "moved reporting off spreadsheets onto a tested data platform"],
    "Analytics & ML": ["put a churn model into the retention team's weekly call list",
                       "built demand forecasting that cut stock-outs",
                       "took a credit-risk model to production with monitoring",
                       "built the pricing analytics behind its quarterly price review",
                       "automated invoice classification for the finance team"],
    "Integration": ["connected ERP, CRM and billing through one API layer",
                    "replaced point-to-point file transfers with event integration",
                    "brought a new partner network into order handling",
                    "integrated a new e-signing service into the sales process",
                    "opened a public API for its larger customers"],
    "Advisory": ["set a two-year data strategy with the leadership team",
                 "assessed the data organisation and its operating model",
                 "prioritised the AI use-case backlog with the business owners",
                 "ran a data-governance review ahead of an audit",
                 "chose a platform vendor through a structured evaluation"],
    "Cloud Migration": ["moved its core services to the cloud without downtime",
                        "migrated the main database and retired a data centre",
                        "re-platformed a legacy ordering system onto managed services",
                        "moved its analytics workloads to a cloud warehouse",
                        "set up the landing zone and moved the first product teams"],
    "Custom Dev": ["built the field-service app its technicians use daily",
                   "delivered a customer self-service portal",
                   "rebuilt an internal pricing tool",
                   "built the booking system its customers now use online",
                   "replaced a paper approval flow with a web app"],
}


def _brief(ind: str, svc: str, k: int) -> str:
    """The k-th brief of an (industry, service) group: 4 clients and 5 kinds of work, rotating
    independently, give 20 distinct briefs before any repeats."""
    client = _CLIENTS[ind][k % len(_CLIENTS[ind])]
    return f"{client[0].upper()}{client[1:]}: {_WORK[svc][k % len(_WORK[svc])]}."


_BASE_EFFORT = {"Advisory": 22, "Analytics & ML": 60, "Integration": 75, "Data Platform": 100, "Cloud Migration": 115, "Custom Dev": 135}
_DEAL_MULT = {"S": 0.55, "M": 0.85, "L": 1.25, "XL": 1.8}
_CPX_MULT = {"Low": 0.8, "Medium": 1.0, "High": 1.35}
_SEN_MULT = {"junior-heavy": 1.2, "balanced": 1.0, "senior-heavy": 0.82}
# Win odds: a believable B2B base (about 21% of pursued deals won) and each driver as an
# odds multiplier, so stacked strengths land near 50%, not at a certain-looking 90%+.
_BASE_WIN = 0.12
_LEAD_WIN_OR = {"Referral": 3.0, "Partner": 2.2, "Inbound": 1.3, "Event": 0.9, "Outbound": 0.55}


def _odds(p: float) -> float:
    return p / (1 - p)


def _prob(o: float) -> float:
    return o / (1 + o)


def build_engagements(rng: random.Random) -> list[dict]:
    rows = []
    seen: dict[tuple[str, str], int] = {}
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

        # win probability from discrete drivers, as odds multipliers on the base
        o = _odds(_BASE_WIN) * _LEAD_WIN_OR[lead]
        if (ind, svc) in GOOD_FIT: o *= 1.8
        if (ind, svc) in BAD_FIT: o *= 0.5
        if rel == "Existing client": o *= 1.6
        if comp == "Sole-source": o *= 1.5
        if cpx == "High": o *= 0.75
        if deal == "XL": o *= 0.8
        p = _prob(o)
        outcome = "won" if rng.random() < p else "lost"

        # effort_days (the numeric to _estimate)
        eff = _BASE_EFFORT[svc] * _DEAL_MULT[deal] * _CPX_MULT[cpx] * _SEN_MULT[sen]
        eff = int(eff * rng.uniform(0.85, 1.15))
        dur = max(2, int(eff / rng.uniform(8, 16)))

        k = seen.get((ind, svc), 0)  # this row's position in its (industry, service) group
        seen[(ind, svc)] = k + 1
        rows.append({
            "engagement_id": f"ENG-{ids[i]}",
            "client_industry": ind, "client_size": size, "service_line": svc,
            "deal_size_band": deal, "engagement_model": model, "complexity": cpx,
            "team_seniority": sen, "region": reg, "lead_source": lead,
            "relationship": rel, "competitive": comp,
            "brief": _brief(ind, svc, k),
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

# Reply and meeting odds: believable outreach (about 3% of touches book a meeting overall;
# a personalised warm intro ~18%, a generic cold email under 1%), each factor an odds multiplier.
_BASE_REPLY, _BASE_MEETING = 0.06, 0.30
_CH_REPLY = {"Warm intro": 4.0, "LinkedIn": 1.3, "Cold email": 0.7, "Cold call": 0.5}
_ANG_REPLY = {"Case study": 1.4, "Referral intro": 1.6, "Benchmark offer": 1.2, "Event follow-up": 1.1, "Pain point": 0.9}
_PER_REPLY = {"High": 1.5, "Medium": 1.1, "Low": 0.8}
_ROLE_REPLY = {"Head of Data": 1.3, "CTO": 1.05, "COO": 0.95, "CEO": 0.7, "Procurement": 0.85}
_SUBJ_REPLY = {"Name-drop": 1.2, "Stat": 1.15, "Question": 1.1, "Direct": 1.0}
_DAY_REPLY = {"Tue": 1.15, "Wed": 1.15, "Thu": 1.05, "Mon": 1.0, "Fri": 0.85}


def build_outreach(rng: random.Random) -> list[dict]:
    rows = []
    ids = rng.sample(range(500000, 500000 + N_OUT * 5), N_OUT)
    for i in range(N_OUT):
        ind = rng.choice(INDUSTRY); size = rng.choices(CLIENT_SIZE, weights=[4, 4, 3])[0]
        role = rng.choice(ROLE); ch = rng.choices(CHANNEL, weights=[2, 4, 5, 3])[0]
        ang = rng.choice(ANGLE); per = rng.choices(PERSONALIZATION, weights=[3, 4, 3])[0]
        subj = rng.choice(SUBJECT); day = rng.choice(DAY); tm = rng.choice(TIME)

        p = _prob(_odds(_BASE_REPLY) * _CH_REPLY[ch] * _ANG_REPLY[ang] * _PER_REPLY[per] * _ROLE_REPLY[role]
                  * _SUBJ_REPLY[subj] * _DAY_REPLY[day])
        replied = rng.random() < p
        # a meeting needs a reply, plus quality
        mp = _prob(_odds(_BASE_MEETING) * (1.5 if ang in ("Case study", "Referral intro") else 1.0)
                   * (1.4 if per == "High" else 1.0))
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
    sc = http.get("/schema").json().get("schema", {})
    live = sc.get(table)
    if live is not None:
        # Recreate the table from its OWN live schema, so its storage engine and column types
        # survive (selecting /api/v2 does not by itself pick the engine); only the rows change.
        if set(live.get("columns", {})) != set(schema["columns"]):
            raise SystemExit(f"refusing: {table}'s live columns differ from the seed's; nothing written")
        schema = live
        assert http.delete(f"/schema/{table}").status_code < 400
    assert http.put(f"/schema/{table}", json=schema).status_code < 400, "create failed"
    after = http.get(f"/schema/{table}").json()
    if live is not None and after.get("engine") != live.get("engine"):
        raise SystemExit(f"{table}: engine changed from {live.get('engine')!r} to {after.get('engine')!r}")
    r = http.post(f"/data/{table}/batch", json=rows)
    assert r.status_code < 400, f"upload {table} failed: {r.text[:200]}"
    cnt = http.post("/_query", json={"from": table, "limit": 0}).json().get("total")
    assert cnt == len(rows), f"{table}: {cnt} != {len(rows)}"
    print(f"  uploaded {table}: {cnt} rows")


def main() -> None:
    import sys
    apply = "--apply" in sys.argv  # a dry run unless asked: this replaces two tables on the live demo's master
    rng = random.Random(SEED)
    cfg = load_config()
    eng = build_engagements(rng)
    out = build_outreach(rng)
    from collections import Counter
    print(f"engagements={len(eng)} win-rate={sum(e['outcome']=='won' for e in eng)/len(eng):.2f}")
    print(f"outreach={len(out)} reply-rate={sum(o['replied']=='yes' for o in out)/len(out):.2f} meeting-rate={sum(o['meeting']=='yes' for o in out)/len(out):.2f}")
    if not apply:
        print("dry run: nothing written. Pass --apply to replace engagements and outreach.")
        return
    with httpx.Client(base_url=f"{cfg.aito_url}/api/{cfg.aito_api_version}", headers={"x-api-key": cfg.aito_key, "content-type": "application/json"}, timeout=60.0) as http:
        _upload(http, "engagements", ENG_SCHEMA, eng)
        _upload(http, "outreach", OUT_SCHEMA, out)
    print("done.")


if __name__ == "__main__":
    main()
