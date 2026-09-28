"""Generate the `support` fixture: support tickets, their resolution steps, and a
KB, linked to the existing Northwind Cloud customers and products.

> **Synthetic data.** Every ticket, step, article and outcome here is generated.
> The effects are planted on purpose and measured by `lifts.py` from the written
> files; nothing here describes a real company.

The Northwind customers and their product usage are not read from Aito: they
are replayed from `scripts/seed_company.py` with its own seed, which reproduces
what is loaded on shared exactly (checked 2026-09-28: 1500/1500 customers and
3531/3531 usage rows identical). So every `customer` and `product` link here
resolves, and adding these tables changes no existing table.

Planted causes (see README.md for the measured lifts):

- **category** from the ticket's words, with shared vocabulary and 12% of tickets
  mixing two topics, so no word is a perfect rule;
- **priority** mostly from urgency words, a little from the category and the
  account's plan and size (measured: only the urgency effect is large);
- **resolution** from the category and the ticket's `issue`, with a policy
  **drift**: from 2026-07-01, 80% of `login` issues are resolved by
  `sso_reconnect` instead of `reset_password` (an SSO rollout); `month` gives
  Aito the time axis;
- **steps**: each resolution is a sequence of steps ending in `done`; the next
  step depends on the previous step and the category (a Markov chain with
  detours);
- **nps_after** (promoter / passive / detractor): detractor risk rises with a
  repeat ticket within 30 days, a slow first response and a Red-health account;
  the **recovery** action is assigned at random, so its effect is causal, and
  the best recovery depends on the account size (credit for SMB, callback for
  Mid-market, CSM outreach for Enterprise);
- **upsell**: offered at random on 30% of tickets from accounts that haven't
  churned; accepted more by high-adoption accounts (`adoption_band`, stored on
  the ticket) on Free/Starter plans, almost never by Red accounts;
- **control**: the ticket `channel` has **no** effect on `nps_after`. Its lift
  must come out at about 1, or the measurement is broken.

    python3 scripts/support_fixture/generate.py      # writes scripts/support_fixture/data/
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import seed_company as nw  # noqa: E402  (the Northwind generator, replayed below)

SEED = 0x5A7707
N_TICKETS = 4000
START, END = date(2026, 3, 2), date(2026, 9, 27)
DRIFT_DATE = date(2026, 7, 1)
OUT = HERE / "data"


def northwind():
    """Replay seed_company.py in its own order: customers, then the per-customer usage."""
    rng = random.Random(nw.SEED)
    customers = nw.build_customers(rng)
    nw.build_feedback(rng, customers)
    nw.build_deals(rng, customers)
    nw.build_tickets(rng, customers)
    usage = nw.build_usage(rng, customers)
    return customers, usage


# ── topics: category → sub-topic → (resolution, phrases) ─────────────
# Phrases share words across categories on purpose ("invoice", "sync", "access",
# "report"), so a single word is evidence, not a rule.
TOPICS = {
    "billing": {
        "double_charge": ("refund", ["I was charged twice for {product} this month",
                                     "there are two charges on my card for the same invoice",
                                     "duplicate payment on our last invoice"]),
        "invoice_question": ("explain_invoice", ["can you explain the {product} line on our invoice",
                                                 "why did our invoice go up this month",
                                                 "the invoice total does not match our seats"]),
        "card_failed": ("update_payment", ["our card payment failed and the account is locked",
                                           "payment declined, how do we update the card",
                                           "billing says the payment method expired"]),
    },
    "bug": {
        "crash": ("engineering_fix", ["{product} crashes when I open it",
                                      "the {product} page throws an error and goes blank",
                                      "getting a 500 error in {product} since this morning"]),
        "wrong_data": ("data_correction", ["the numbers in {product} are wrong",
                                           "{product} shows yesterday's data, not today's",
                                           "the report totals do not match the export"]),
    },
    "how_to": {
        "setup": ("send_guide", ["how do I set up {product} for my team",
                                 "where do I configure alerts in {product}",
                                 "is there a guide for getting started with {product}"]),
        "export": ("send_guide", ["how can I export a report from {product}",
                                  "can I schedule an export to our drive",
                                  "what is the best way to share a dashboard"]),
    },
    "access": {
        "login": ("reset_password", ["I cannot log in to {product}",
                                     "my password does not work anymore",
                                     "locked out of my account after too many attempts"]),
        "permissions": ("adjust_roles", ["a colleague cannot see the {product} workspace",
                                         "how do I give admin access to a new user",
                                         "we need read only access for an auditor"]),
    },
    "performance": {
        "slow": ("optimise_query", ["{product} is really slow today",
                                    "dashboards take a minute to load",
                                    "the report export times out"]),
    },
    "integration": {
        "sync": ("reconnect_integration", ["our CRM sync stopped working",
                                           "the invoice sync to our ERP has failed since Monday",
                                           "{product} webhook calls are failing"]),
        "api": ("api_guidance", ["which API endpoint returns usage per seat",
                                 "we hit the API rate limit, what are the limits",
                                 "how do I authenticate against the {product} API"]),
    },
}
OPENERS = ["Hi,", "Hello team,", "Hey,", "Good morning,", "", "", "Quick question:"]
CLOSERS = ["Thanks!", "Please help.", "Regards,", "Any update would be great.", "", "", "Cheers"]
URGENT = ["urgent", "asap", "blocking our team", "production is down", "right now"]

# Steps per resolution: the canonical path; the chain adds realistic detours.
PATHS = {
    "refund": ["verify_charge", "issue_refund", "confirm_with_customer"],
    "explain_invoice": ["open_invoice", "explain_line_items", "confirm_with_customer"],
    "update_payment": ["verify_account", "send_payment_link", "unlock_account"],
    "engineering_fix": ["reproduce", "collect_logs", "escalate_engineering", "confirm_fix"],
    "data_correction": ["reproduce", "check_pipeline", "rerun_sync", "confirm_fix"],
    "send_guide": ["identify_need", "send_article", "confirm_with_customer"],
    "reset_password": ["verify_identity", "send_reset_link", "confirm_with_customer"],
    "sso_reconnect": ["verify_identity", "check_sso_config", "reconnect_sso", "confirm_with_customer"],
    "adjust_roles": ["verify_admin", "update_roles", "confirm_with_customer"],
    "optimise_query": ["reproduce", "profile_query", "apply_optimisation", "confirm_fix"],
    "reconnect_integration": ["check_integration_status", "rotate_credentials", "rerun_sync", "confirm_fix"],
    "api_guidance": ["identify_need", "send_article", "confirm_with_customer"],
}
DETOURS = ["ask_for_details", "wait_for_customer"]

RECOVERY = ["none", "apology_credit", "priority_callback", "csm_outreach"]
# Detractor-risk change per recovery, by account size: credits work for SMB,
# a CSM call for Enterprise, a priority callback in between.
_RECOVERY_EFFECT = {
    "SMB":        {"none": 0.0, "apology_credit": -0.14, "priority_callback": -0.06, "csm_outreach": -0.02},
    "Mid-market": {"none": 0.0, "apology_credit": -0.03, "priority_callback": -0.18, "csm_outreach": -0.03},
    "Enterprise": {"none": 0.0, "apology_credit": -0.01, "priority_callback": -0.06, "csm_outreach": -0.16},
}
CHANNELS = ["email", "chat", "portal", "phone"]
FIRST_RESPONSE = ["<1h", "1-4h", "4-24h", ">24h"]


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def build_kb():
    """One or two articles per resolution, titled from its path."""
    rows = []
    for i, (res, path) in enumerate(sorted(PATHS.items())):
        for variant in ("guide", "faq") if res in ("send_guide", "api_guidance", "reset_password") else ("guide",):
            rows.append({"article_id": f"KB-{i:02d}{variant[0]}", "resolution": res,
                         "title": f"{res.replace('_', ' ').capitalize()} ({variant})",
                         "body": " then ".join(s.replace("_", " ") for s in path) + "."})
    return rows


def build_tickets(rng, customers, usage, kb, control_leak: float = 0.0):
    """`control_leak` plants a channel effect on detractor risk. It is 0 for the
    fixture; the test sets it to prove the control check can fail."""
    by_cust_usage: dict[str, list[dict]] = {}
    for u in usage:
        by_cust_usage.setdefault(u["customer"], []).append(u)
    kb_by_res: dict[str, list[str]] = {}
    for a in kb:
        kb_by_res.setdefault(a["resolution"], []).append(a["article_id"])

    days = (END - START).days
    stamps = sorted(START + timedelta(days=rng.randrange(days + 1)) for _ in range(N_TICKETS))
    last_ticket: dict[str, date] = {}
    tickets, steps = [], []
    for i, day in enumerate(stamps):
        c = rng.choice(customers)
        cat = rng.choices(list(TOPICS), weights=[5, 4, 4, 3, 2, 3])[0]
        sub = rng.choice(list(TOPICS[cat]))
        res, phrases = TOPICS[cat][sub]
        if cat == "access" and sub == "login" and day >= DRIFT_DATE and rng.random() < 0.8:
            res = "sso_reconnect"  # the planted drift: an SSO rollout changes the fix
        cust_products = [u["product"] for u in by_cust_usage.get(c["customer_id"], [])] or [c["primary_product"]]
        product = rng.choice(cust_products)
        pname = next(p["name"] for p in nw.PRODUCTS if p["product_id"] == product)

        urgent = rng.random() < 0.18
        parts = [rng.choice(OPENERS), rng.choice(phrases).format(product=pname)]
        if rng.random() < 0.12:  # a second topic in the same ticket: ambiguity
            ocat = rng.choice([k for k in TOPICS if k != cat])
            parts.append("also " + rng.choice(rng.choice(list(TOPICS[ocat].values()))[1]).format(product=pname))
        if urgent:
            parts.append(rng.choice(URGENT))
        parts.append(rng.choice(CLOSERS))
        text = " ".join(p for p in parts if p).replace("  ", " ")

        # priority: urgency words, category, plan and size
        hp = 0.08 + (0.45 if urgent else 0) + {"bug": 0.12, "access": 0.08, "billing": 0.04}.get(cat, 0) \
            + {"Enterprise": 0.10, "Pro": 0.04}.get(c["plan"], 0) + {"Enterprise": 0.06}.get(c["size"], 0)
        r = rng.random()
        priority = "high" if r < min(0.9, hp) else ("normal" if r < min(0.95, hp + 0.55) else "low")

        channel = rng.choice(CHANNELS)
        frt = rng.choices(FIRST_RESPONSE, weights=[3, 4, 3, 2] if priority != "high" else [5, 4, 2, 1])[0]
        repeat = c["customer_id"] in last_ticket and (day - last_ticket[c["customer_id"]]).days <= 30
        last_ticket[c["customer_id"]] = day
        sender = f"{rng.choice(['it', 'ops', 'finance', 'admin', 'hello'])}@{_slug(c['name'])}{c['customer_id'][-3:]}.example" \
            if rng.random() < 0.6 else f"user{rng.randrange(10000)}@freemail.example"

        # outcome: detractor risk (channel deliberately absent: the control)
        recovery = rng.choice(RECOVERY)
        d = 0.14 + (0.16 if repeat else 0) + {">24h": 0.14, "4-24h": 0.05}.get(frt, 0) \
            + {"Red": 0.15, "Yellow": 0.05}.get(c["health"], 0) + _RECOVERY_EFFECT[c["size"]][recovery] \
            + (control_leak if channel == "chat" else 0.0)
        d = min(0.9, max(0.02, d))
        r = rng.random()
        nps_after = "detractor" if r < d else ("promoter" if r > d + 0.35 else "passive")
        csat = "bad" if nps_after == "detractor" and rng.random() < 0.7 else ("good" if nps_after == "promoter" or rng.random() < 0.5 else "neutral")

        # the account's product adoption, stored on the ticket: usage links to
        # customers, not the other way, so a ticket could not reach it by a link
        us = by_cust_usage.get(c["customer_id"], [])
        adoption = sum(u["active"] == "yes" for u in us) / len(us) if us else 0.0
        adoption_band = "high" if adoption >= 0.67 else ("low" if adoption < 0.34 else "medium")

        # upsell: offered at random to accounts that haven't churned; accepted by
        # adoption and plan, almost never by Red accounts
        offered = c["churned"] == "no" and rng.random() < 0.30
        accepted = None
        if offered:
            pa = 0.05 + 0.30 * adoption + {"Free": 0.12, "Starter": 0.08}.get(c["plan"], 0)
            if c["health"] == "Red":
                pa = 0.02
            accepted = "yes" if rng.random() < pa else "no"

        tid = f"SUP-{i + 1:05d}"
        created = datetime.combine(day, datetime.min.time()) + timedelta(minutes=rng.randrange(8 * 60, 18 * 60))
        tickets.append({
            "ticket_id": tid, "created_at": created.isoformat(timespec="minutes"), "month": day.strftime("%Y-%m"),
            "text": text, "issue": sub, "adoption_band": adoption_band,
            "sender_domain": sender.split("@")[1], "channel": channel,
            "customer": c["customer_id"], "product": product,
            "category": cat, "priority": priority, "resolution": res,
            "kb_article": rng.choice(kb_by_res[res]) if rng.random() < 0.85 else None,
            "first_response": frt, "repeat_30d": "yes" if repeat else "no",
            "recovery": recovery, "nps_after": nps_after, "csat_band": csat,
            "upsell_offered": "yes" if offered else "no", "upsell_accepted": accepted,
        })

        # steps: the canonical path, with detours (the Markov noise)
        path, t, prev, n = PATHS[res] + ["done"], created, "start", 0
        for step in path:
            if step != "done" and rng.random() < 0.15:
                seq = [rng.choice(DETOURS), step]
            else:
                seq = [step]
            for action in seq:
                n += 1
                t += timedelta(minutes=rng.randrange(5, 240))
                steps.append({"step_id": f"{tid}-{n}", "ticket": tid, "step_no": n, "category": cat,
                              "previous_action": prev, "action": action, "created_at": t.isoformat(timespec="minutes")})
                prev = action
    return tickets, steps


def main(out: Path = OUT) -> None:
    customers, usage = northwind()
    rng = random.Random(SEED)
    kb = build_kb()
    tickets, steps = build_tickets(rng, customers, usage, kb)
    out.mkdir(exist_ok=True)
    for name, rows in (("kb_articles", kb), ("support_tickets", tickets), ("support_steps", steps)):
        (out / f"{name}.json").write_text(json.dumps(rows, indent=0, sort_keys=True) + "\n")
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
