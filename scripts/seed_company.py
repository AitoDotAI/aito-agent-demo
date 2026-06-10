"""Seed the 'Northwind Cloud' 360° company dataset into Aito — a LINKED model.

A single `customers` master holds the shared entity (industry, size, plan,
health, csm_motion, churn…) referenced by every other domain via an Aito link.
A `products` catalog is linked from the situations that touch a product. So the
360 view is real: pick a customer and you can pull their deals, tickets, usage,
invoices and feedback — and predictions on a child table can use the linked
customer's attributes (verified: _predict where {customer.size: …} works).

    customers (master)  → Churn        lever: csm_motion
    products  (catalog)
    feedback            → NPS          lever: theme
    deals               → Conversion   lever: nurture_track
    tickets             → CSAT         lever: channel
    usage               → Adoption     lever: onboarding_push
    invoices            → On-time/exp  lever: term

Every child row links to a real customer (and product where relevant), so the
customer's attributes genuinely drive the child KPI. Discrete features + baked
correlations so Aito's probabilities are reliable.

    uv run python scripts/seed_company.py
"""

from __future__ import annotations

import random

import httpx

from src.config import load_config

SEED = 0xC0FFEE
N_CUST = 1500
N_FEEDBACK = 3000
N_DEALS = 2200
N_TICKETS = 3000
N_INVOICES = 2600

INDUSTRY = ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"]
SIZE = ["SMB", "Mid-market", "Enterprise"]
PLAN = ["Free", "Starter", "Pro", "Enterprise"]
REGION = ["Helsinki", "Stockholm", "Berlin", "London", "Remote"]
SEATS = ["1-5", "6-20", "21-100", "100+"]


def _pick(rng, opts, w=None):
    return rng.choices(opts, weights=w)[0] if w else rng.choice(opts)


# ── products catalog ───────────────────────────────────────────────
PRODUCTS = [
    {"product_id": "PRD-dashboards", "name": "Dashboards", "category": "Analytics", "tier": "Core"},
    {"product_id": "PRD-reports", "name": "Reports", "category": "Analytics", "tier": "Core"},
    {"product_id": "PRD-api", "name": "API", "category": "Platform", "tier": "Core"},
    {"product_id": "PRD-automations", "name": "Automations", "category": "Workflow", "tier": "Pro"},
    {"product_id": "PRD-integrations", "name": "Integrations", "category": "Platform", "tier": "Pro"},
    {"product_id": "PRD-mobile", "name": "Mobile", "category": "Access", "tier": "Core"},
    {"product_id": "PRD-forecasting", "name": "Forecasting", "category": "Analytics", "tier": "Enterprise"},
    {"product_id": "PRD-governance", "name": "Governance", "category": "Platform", "tier": "Enterprise"},
]
_PID = [p["product_id"] for p in PRODUCTS]


# ── customers (Churn) — the shared master ──────────────────────────
TENURE = ["<3mo", "3-12mo", "1-2y", "2y+"]
ONBOARDING = ["Completed", "Partial", "None"]
HEALTH = ["Green", "Yellow", "Red"]
NPS_BAND = ["promoter", "passive", "detractor"]
CSM_MOTION = ["None", "Pooled", "Dedicated", "Exec-sponsor"]   # churn lever
_PLAN_CHURN = {"Free": 0.20, "Starter": 0.10, "Pro": -0.05, "Enterprise": -0.14}
_HEALTH_CHURN = {"Green": -0.18, "Yellow": 0.04, "Red": 0.30}
_ONB_CHURN = {"Completed": -0.12, "Partial": 0.06, "None": 0.22}
_TEN_CHURN = {"<3mo": 0.16, "3-12mo": 0.04, "1-2y": -0.05, "2y+": -0.12}
_NPS_CHURN = {"promoter": -0.16, "passive": 0.02, "detractor": 0.22}
# csm_motion's churn effect DEPENDS ON SIZE — so the recommended motion differs by
# segment: SMB barely needs more than Pooled; Enterprise retention hinges on Exec-sponsor.
_CSM_CHURN_BY_SIZE = {
    "SMB":        {"None": 0.10, "Pooled": -0.05, "Dedicated": -0.12, "Exec-sponsor": -0.06},
    "Mid-market": {"None": 0.12, "Pooled": -0.01, "Dedicated": -0.13, "Exec-sponsor": -0.17},
    "Enterprise": {"None": 0.16, "Pooled": 0.03,  "Dedicated": -0.14, "Exec-sponsor": -0.26},
}
_PLAN_MRR = {"Free": 0, "Starter": 90, "Pro": 600, "Enterprise": 2800}
_SIZE_MULT = {"SMB": 1.0, "Mid-market": 2.2, "Enterprise": 5.0}
_SEAT_MULT = {"1-5": 0.7, "6-20": 1.0, "21-100": 1.8, "100+": 3.2}
_NAMES = ["Acme", "Globex", "Initech", "Umbra", "Stark", "Wayne", "Hooli", "Pied Piper", "Soylent", "Vehement",
          "Massive", "Vandelay", "Wonka", "Cyberdyne", "Tyrell", "Gekko", "Oscorp", "Nakatomi", "Bluth", "Dunder"]


def build_customers(rng):
    rows, ids = [], rng.sample(range(100000, 100000 + N_CUST * 6), N_CUST)
    for i in range(N_CUST):
        ind = _pick(rng, INDUSTRY); size = _pick(rng, SIZE, [5, 4, 3]); plan = _pick(rng, PLAN, [3, 4, 4, 2])
        region = _pick(rng, REGION); tenure = _pick(rng, TENURE, [3, 4, 4, 3]); seats = _pick(rng, SEATS, [4, 4, 3, 2])
        onb = _pick(rng, ONBOARDING, [5, 3, 2]); health = _pick(rng, HEALTH, [5, 3, 2])
        nps = _pick(rng, NPS_BAND, [4, 4, 3]); csm = _pick(rng, CSM_MOTION, [3, 3, 3, 3])
        primary = _pick(rng, PRODUCTS)["product_id"]
        p = 0.16 + _PLAN_CHURN[plan] + _HEALTH_CHURN[health] + _ONB_CHURN[onb] + _TEN_CHURN[tenure] \
            + _NPS_CHURN[nps] + _CSM_CHURN_BY_SIZE[size][csm]
        churned = "yes" if rng.random() < min(0.93, max(0.02, p)) else "no"
        mrr = int(_PLAN_MRR[plan] * _SIZE_MULT[size] * _SEAT_MULT[seats] * rng.uniform(0.8, 1.25))
        rows.append({"customer_id": f"ACC-{ids[i]}", "name": f"{_pick(rng, _NAMES)} {ind[:3]}", "industry": ind,
                     "size": size, "plan": plan, "region": region, "tenure_band": tenure, "seats_band": seats,
                     "onboarding": onb, "health": health, "nps_band": nps, "csm_motion": csm,
                     "primary_product": primary, "mrr_eur": mrr, "churned": churned})
    return rows


# ── feedback (NPS) ─────────────────────────────────────────────────
SURVEY = ["NPS", "CSAT", "CES"]
THEME = ["Onboarding", "Support", "Pricing", "Product", "Performance", "Docs"]   # NPS lever
CHANNEL_FB = ["in-app", "email", "CSM"]
# which theme drives detractors DEPENDS ON SIZE — so "the theme to fix" differs by
# segment: SMB detracts on Pricing, Enterprise on Performance/Support.
_THEME_SCORE_BY_SIZE = {
    "SMB":        {"Pricing": 0.28, "Onboarding": -0.26, "Product": -0.08, "Support": 0.08, "Performance": 0.08, "Docs": 0.02},
    "Mid-market": {"Support": 0.22, "Product": -0.18, "Performance": 0.14, "Pricing": 0.10, "Onboarding": -0.06, "Docs": 0.0},
    "Enterprise": {"Performance": 0.26, "Support": 0.20, "Product": -0.18, "Onboarding": -0.02, "Pricing": 0.02, "Docs": 0.0},
}
_PLAN_SCORE = {"Free": 0.10, "Starter": 0.04, "Pro": -0.04, "Enterprise": -0.10}


def build_feedback(rng, customers):
    rows, ids = [], rng.sample(range(700000, 700000 + N_FEEDBACK * 6), N_FEEDBACK)
    for i in range(N_FEEDBACK):
        c = _pick(rng, customers); theme = _pick(rng, THEME)
        d = min(0.9, max(0.05, 0.30 + _THEME_SCORE_BY_SIZE[c["size"]][theme] + _PLAN_SCORE[c["plan"]]))
        r = rng.random()
        score = "detractor" if r < d else ("promoter" if r > 1 - (0.45 - (d - 0.3)) else "passive")
        resolved = "yes" if rng.random() < (0.4 if score == "detractor" else 0.8) else "no"
        rows.append({"feedback_id": f"FB-{ids[i]}", "customer": c["customer_id"], "survey_type": _pick(rng, SURVEY),
                     "score_band": score, "theme": theme, "channel": _pick(rng, CHANNEL_FB, [5, 4, 2]), "resolved": resolved})
    return rows


# ── deals (Conversion) ─────────────────────────────────────────────
SOURCE = ["Inbound", "Outbound", "Partner", "Event", "Referral"]
NURTURE = ["Self-serve", "Guided trial", "CSM-led", "Webinar", "Partner"]   # conversion lever
TRIAL_LEN = ["7d", "14d", "30d"]
_SRC_CONV = {"Referral": 0.18, "Partner": 0.10, "Inbound": 0.04, "Event": -0.02, "Outbound": -0.12}
# nurture_track's conversion effect DEPENDS ON SIZE: SMB converts on low-touch
# self-serve/guided; Enterprise needs CSM-led / Partner.
_NUR_CONV_BY_SIZE = {
    "SMB":        {"Self-serve": 0.16, "Guided trial": 0.14, "CSM-led": 0.0,  "Webinar": 0.06, "Partner": 0.02},
    "Mid-market": {"Self-serve": -0.04, "Guided trial": 0.12, "CSM-led": 0.14, "Webinar": 0.06, "Partner": 0.10},
    "Enterprise": {"Self-serve": -0.18, "Guided trial": 0.0,  "CSM-led": 0.22, "Webinar": -0.02, "Partner": 0.18},
}
_SIZE_CONV = {"SMB": 0.04, "Mid-market": 0.0, "Enterprise": -0.06}


def build_deals(rng, customers):
    rows, ids = [], rng.sample(range(200000, 200000 + N_DEALS * 6), N_DEALS)
    for i in range(N_DEALS):
        c = _pick(rng, customers); src = _pick(rng, SOURCE, [4, 4, 2, 2, 3]); nur = _pick(rng, NURTURE, [3, 3, 3, 3, 3])
        prod = _pick(rng, PRODUCTS)["product_id"]
        p = 0.30 + _SRC_CONV[src] + _NUR_CONV_BY_SIZE[c["size"]][nur] + _SIZE_CONV[c["size"]]
        converted = "yes" if rng.random() < min(0.9, max(0.04, p)) else "no"
        rows.append({"deal_id": f"DEAL-{ids[i]}", "customer": c["customer_id"], "product": prod, "source": src,
                     "nurture_track": nur, "trial_length": _pick(rng, TRIAL_LEN, [3, 5, 3]), "converted": converted})
    return rows


# ── tickets (CSAT) ─────────────────────────────────────────────────
CATEGORY = ["Bug", "How-to", "Billing", "Outage", "Feature-req"]
PRIORITY = ["Low", "Medium", "High"]
CHANNEL_T = ["in-app", "email", "chat", "phone"]   # CSAT lever
FRT = ["<1h", "1-8h", "8-24h", ">24h"]
_CAT_CSAT = {"How-to": 0.12, "Feature-req": 0.0, "Bug": -0.06, "Billing": -0.12, "Outage": -0.16}
# best support channel DEPENDS ON SIZE: SMB loves chat/in-app; Enterprise wants phone.
_CH_CSAT_BY_SIZE = {
    "SMB":        {"chat": 0.16, "in-app": 0.10, "phone": 0.0,  "email": -0.04},
    "Mid-market": {"chat": 0.10, "phone": 0.08, "in-app": 0.04, "email": -0.06},
    "Enterprise": {"phone": 0.22, "chat": -0.04, "in-app": -0.04, "email": -0.12},
}
_FRT_CSAT = {"<1h": 0.16, "1-8h": 0.06, "8-24h": -0.06, ">24h": -0.18}


def build_tickets(rng, customers):
    rows, ids = [], rng.sample(range(300000, 300000 + N_TICKETS * 6), N_TICKETS)
    for i in range(N_TICKETS):
        c = _pick(rng, customers); cat = _pick(rng, CATEGORY, [4, 5, 3, 2, 3]); ch = _pick(rng, CHANNEL_T, [3, 3, 3, 3])
        frt = _pick(rng, FRT, [3, 4, 3, 2]); prod = _pick(rng, PRODUCTS)["product_id"]
        g = min(0.92, max(0.05, 0.55 + _CAT_CSAT[cat] + _CH_CSAT_BY_SIZE[c["size"]][ch] + _FRT_CSAT[frt]))
        csat = "good" if rng.random() < g else ("bad" if rng.random() < 0.55 else "neutral")
        resolved = "yes" if rng.random() < (0.9 if csat == "good" else 0.5) else "no"
        rows.append({"ticket_id": f"TKT-{ids[i]}", "customer": c["customer_id"], "product": prod, "category": cat,
                     "priority": _pick(rng, PRIORITY, [4, 4, 2]), "channel": ch, "first_response": frt,
                     "csat_band": csat, "resolved": resolved})
    return rows


# ── usage (Adoption) — one row per customer×product they hold ──────
ADOPTION = ["none", "trial", "active", "power"]
ONB_PUSH = ["None", "Email-only", "Guided", "Workshop"]   # adoption lever
_ADOPT_ACTIVE = {"none": -0.35, "trial": -0.10, "active": 0.20, "power": 0.35}
# onboarding push that lands adoption DEPENDS ON SIZE: SMB self-serves with Guided/
# Email; Enterprise needs a Workshop.
_PUSH_ACTIVE_BY_SIZE = {
    "SMB":        {"None": -0.10, "Email-only": 0.08, "Guided": 0.10, "Workshop": 0.02},
    "Mid-market": {"None": -0.12, "Email-only": 0.0,  "Guided": 0.12, "Workshop": 0.14},
    "Enterprise": {"None": -0.14, "Email-only": -0.06, "Guided": 0.04, "Workshop": 0.24},
}
_TIER_ACTIVE = {"Core": 0.08, "Pro": 0.0, "Enterprise": -0.04}
_TIER = {p["product_id"]: p["tier"] for p in PRODUCTS}


def build_usage(rng, customers):
    rows, n = [], 0
    for c in customers:
        for prod in rng.sample(_PID, rng.choices([1, 2, 3, 4], weights=[3, 4, 3, 2])[0]):
            adopt = _pick(rng, ADOPTION, [3, 3, 4, 2]); push = _pick(rng, ONB_PUSH, [3, 3, 3, 3])
            p = 0.45 + _ADOPT_ACTIVE[adopt] + _PUSH_ACTIVE_BY_SIZE[c["size"]][push] + _TIER_ACTIVE[_TIER[prod]]
            active = "yes" if rng.random() < min(0.95, max(0.03, p)) else "no"
            rows.append({"usage_id": f"USE-{n:06d}", "customer": c["customer_id"], "product": prod,
                         "adoption_band": adopt, "onboarding_push": push, "active": active})
            n += 1
    return rows


# ── invoices (Finance: on-time / expansion) ────────────────────────
TERM = ["Monthly", "Annual"]   # finance lever
AMOUNT = ["S", "M", "L", "XL"]
# annual billing helps on-time payment far more for larger accounts (procurement);
# for SMB the term barely matters — so the lever's lift is segment-specific.
_TERM_OK_BY_SIZE = {
    "SMB":        {"Monthly": 0.0,  "Annual": 0.05},
    "Mid-market": {"Monthly": -0.06, "Annual": 0.12},
    "Enterprise": {"Monthly": -0.10, "Annual": 0.18},
}
_PLAN_OK = {"Free": -0.10, "Starter": -0.02, "Pro": 0.06, "Enterprise": 0.14}
_SIZE_EXP = {"SMB": -0.04, "Mid-market": 0.04, "Enterprise": 0.12}


def build_invoices(rng, customers):
    rows, ids = [], rng.sample(range(500000, 500000 + N_INVOICES * 6), N_INVOICES)
    for i in range(N_INVOICES):
        c = _pick(rng, customers); term = _pick(rng, TERM, [5, 4])
        ok = 0.62 + _TERM_OK_BY_SIZE[c["size"]][term] + _PLAN_OK[c["plan"]]
        exp = 0.12 + _SIZE_EXP[c["size"]] + _PLAN_OK[c["plan"]] * 0.5
        status = "overdue" if rng.random() > min(0.95, max(0.4, ok)) else ("expansion" if rng.random() < max(0.03, exp) else "paid")
        rows.append({"invoice_id": f"INV-{ids[i]}", "customer": c["customer_id"], "term": term,
                     "amount_band": _pick(rng, AMOUNT, [4, 5, 3, 2]), "status": status})
    return rows


# ── schemas (links declared so predictions can traverse them) ──────
def _cols(d, ints=(), links=None):
    links = links or {}
    out = {}
    for k in d:
        if k in links:
            out[k] = {"type": "String", "link": links[k]}
        else:
            out[k] = {"type": "Int"} if k in ints else {"type": "String"}
    return {"type": "table", "columns": out}


def _link_cust(k="customer"):
    return {k: "customers.customer_id"}


# Drop order: children (which link to customers/products) BEFORE the parents,
# or Aito refuses the delete (the link is a foreign-key guard).
_DROP_ORDER = ["feedback", "invoices", "usage", "tickets", "deals", "customers", "products"]


def _drop_all(http):
    sc = http.get("/api/v1/schema").json().get("schema", {})
    for table in _DROP_ORDER:
        if table in sc:
            assert http.delete(f"/api/v1/schema/{table}").status_code < 400, f"drop {table} failed"


def _upload(http, table, rows, schema):
    assert http.put(f"/api/v1/schema/{table}", json=schema).status_code < 400, f"create {table} failed"
    r = http.post(f"/api/v1/data/{table}/batch", json=rows)
    assert r.status_code < 400, f"upload {table} failed: {r.text[:200]}"
    cnt = http.post("/api/v1/_query", json={"from": table, "limit": 0}).json().get("total")
    assert cnt == len(rows), f"{table}: {cnt} != {len(rows)}"
    print(f"  uploaded {table}: {cnt} rows")


def main() -> None:
    rng = random.Random(SEED)
    cfg = load_config()
    customers = build_customers(rng)
    feedback = build_feedback(rng, customers)
    deals = build_deals(rng, customers)
    tickets = build_tickets(rng, customers)
    usage = build_usage(rng, customers)
    invoices = build_invoices(rng, customers)
    print(f"customers={len(customers)} churn={sum(c['churned']=='yes' for c in customers)/len(customers):.2f}")
    print(f"deals={len(deals)} conv={sum(d['converted']=='yes' for d in deals)/len(deals):.2f}")
    print(f"tickets={len(tickets)} good-csat={sum(t['csat_band']=='good' for t in tickets)/len(tickets):.2f}")
    print(f"usage={len(usage)} active={sum(u['active']=='yes' for u in usage)/len(usage):.2f}")
    print(f"invoices={len(invoices)} overdue={sum(i['status']=='overdue' for i in invoices)/len(invoices):.2f}")

    pcust = _cols(customers[0].keys(), ints=("mrr_eur",), links={"primary_product": "products.product_id"})
    pprod = _cols(PRODUCTS[0].keys())
    with httpx.Client(base_url=cfg.aito_url, headers={"x-api-key": cfg.aito_key, "content-type": "application/json"}, timeout=120.0) as http:
        _drop_all(http)  # children before parents
        # products + customers first (link targets must exist)
        _upload(http, "products", PRODUCTS, pprod)
        _upload(http, "customers", customers, pcust)
        _upload(http, "feedback", feedback, _cols(feedback[0].keys(), links=_link_cust()))
        _upload(http, "deals", deals, _cols(deals[0].keys(), links={**_link_cust(), "product": "products.product_id"}))
        _upload(http, "tickets", tickets, _cols(tickets[0].keys(), links={**_link_cust(), "product": "products.product_id"}))
        _upload(http, "usage", usage, _cols(usage[0].keys(), links={**_link_cust(), "product": "products.product_id"}))
        _upload(http, "invoices", invoices, _cols(invoices[0].keys(), links=_link_cust()))
    print("done.")


if __name__ == "__main__":
    main()
