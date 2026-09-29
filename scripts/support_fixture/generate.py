"""Generate the `support` fixture: a B2B support desk for Northwind Cloud's
accounts. Named contacts, their tickets, the resolution steps, and a KB, linked to
the existing Northwind customers and products.

> **Synthetic data.** Every contact, ticket, step, article and outcome here is
> generated. The effects are planted on purpose and measured by `lifts.py` from
> the written files; nothing here describes a real company or person.

The Northwind customers and their product usage are not read from Aito: they
are replayed from `scripts/seed_company.py` with its own seed, which reproduces
what is loaded on shared exactly (checked 2026-09-28: 1500/1500 customers and
3531/3531 usage rows identical). So every link resolves, and adding these tables
changes no existing table.

The desk serves 240 active accounts (weighted towards larger ones), about 50
tickets each over a year, which is what makes an account's history useful.
Planted causes (see README.md for the measured lifts):

- **who**: a ticket comes from a known contact (a lookup, no prediction needed),
  or, 8% of the time, from a new address at the account's own domain;
- **product** from the account's own products, and named in most tickets;
- **category** from the contact's role (finance writes about billing, developers
  about integrations and the API), the product, and the ticket's words; each
  account also has a **recurring issue** that is 30% of its tickets;
- **priority** from urgency words, bugs and the Enterprise plan's SLA;
- **resolution** from the category and the `issue`, with a policy **drift**: from
  2026-07-01, 80% of `login` issues are resolved by `sso_reconnect` instead of
  `reset_password` (an SSO rollout); `month` gives Aito the time axis;
- **steps**: each resolution is a sequence of steps ending in `done`, with detours;
- **nps_after**: detractor risk rises when the same issue comes back within 30
  days, with a slow first response and with a Red-health account; the
  **recovery** action is assigned at random, so its effect is causal, and the
  best one depends on the account size;
- **upsell**: offered at random on 30% of tickets from accounts that haven't
  churned; accepted more by high-adoption accounts on Free/Starter plans,
  almost never by Red accounts;
- **control**: the ticket `channel` has **no** effect on `nps_after`.

    python3 scripts/support_fixture/generate.py
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
N_ACCOUNTS = 240
N_TICKETS = 12000
START, END = date(2025, 10, 1), date(2026, 9, 27)
DRIFT_DATE = date(2026, 7, 1)
OUT = HERE / "data"
#: the held-out incoming queue ships with the app (src/data), since data/ is not committed
INCOMING = HERE.parent.parent / "src" / "data" / "support_incoming.json"
HOLDOUT = 300


def northwind():
    """Replay seed_company.py in its own order: customers, then the per-customer usage."""
    rng = random.Random(nw.SEED)
    customers = nw.build_customers(rng)
    nw.build_feedback(rng, customers)
    nw.build_deals(rng, customers)
    nw.build_tickets(rng, customers)
    usage = nw.build_usage(rng, customers)
    return customers, usage


# ── topics: category → issue → (resolution, phrases) ─────────────────
# Phrases share words across categories on purpose ("invoice", "sync", "access",
# "report"), so a single word is evidence, not a rule.
TOPICS = {
    "billing": {
        "double_charge": ("refund", ["I was charged twice for {product} this month",
                                     "there are two charges on our card for the same invoice",
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
CATS = list(TOPICS)
ISSUES = [(c, i) for c in TOPICS for i in TOPICS[c]]
OPENERS = ["Hi,", "Hello team,", "Hey,", "Good morning,", "", "", "Quick question:"]
CLOSERS = ["Thanks!", "Please help.", "Regards,", "Any update would be great.", "", "", "Cheers"]
URGENT = ["urgent", "asap", "blocking our team", "production is down", "right now"]

#: who writes about what: category weights by the contact's role
ROLES = ["it_admin", "finance", "ops", "analyst", "developer"]
ROLE_CAT = {
    "it_admin":  {"billing": 1, "bug": 2, "how_to": 1, "access": 6, "performance": 2, "integration": 2},
    "finance":   {"billing": 8, "bug": 1, "how_to": 1, "access": 1, "performance": 0.5, "integration": 1},
    "ops":       {"billing": 1, "bug": 3, "how_to": 3, "access": 2, "performance": 3, "integration": 1},
    "analyst":   {"billing": 0.5, "bug": 4, "how_to": 4, "access": 1, "performance": 3, "integration": 0.5},
    "developer": {"billing": 0.5, "bug": 3, "how_to": 1, "access": 1, "performance": 2, "integration": 7},
}
#: which products break how: category weights by the product's category
PRODUCT_CAT = {
    "Analytics": {"billing": 1, "bug": 3, "how_to": 3, "access": 1, "performance": 3, "integration": 0.5},
    "Platform":  {"billing": 1, "bug": 2, "how_to": 1, "access": 1, "performance": 1, "integration": 5},
    "Workflow":  {"billing": 1, "bug": 3, "how_to": 3, "access": 1, "performance": 1, "integration": 2},
    "Access":    {"billing": 1, "bug": 1, "how_to": 1, "access": 6, "performance": 1, "integration": 0.5},
}
FIRST = ["Anna", "Mikko", "Laura", "Jussi", "Sara", "Ville", "Emma", "Olli", "Noora", "Teemu", "Aino", "Lauri"]
LAST = ["Virtanen", "Korhonen", "Nieminen", "Makinen", "Hamalainen", "Laine", "Koskinen", "Heikkinen", "Lehtonen"]

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
# a callback for Mid-market, a CSM call for Enterprise.
_RECOVERY_EFFECT = {
    "SMB":        {"none": 0.0, "apology_credit": -0.14, "priority_callback": -0.06, "csm_outreach": -0.02},
    "Mid-market": {"none": 0.0, "apology_credit": -0.03, "priority_callback": -0.18, "csm_outreach": -0.03},
    "Enterprise": {"none": 0.0, "apology_credit": -0.01, "priority_callback": -0.06, "csm_outreach": -0.16},
}
CHANNELS = ["email", "chat", "portal", "phone"]
FIRST_RESPONSE = ["<1h", "1-4h", "4-24h", ">24h"]


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def domain_of(c: dict) -> str:
    return f"{_slug(c['name'])}{c['customer_id'][4:]}.example"  # the numeric id keeps it unique


def build_kb():
    """One or two articles per resolution, titled from its path."""
    rows = []
    for i, (res, path) in enumerate(sorted(PATHS.items())):
        for variant in ("guide", "faq") if res in ("send_guide", "api_guidance", "reset_password") else ("guide",):
            rows.append({"article_id": f"KB-{i:02d}{variant[0]}", "resolution": res,
                         "title": f"{res.replace('_', ' ').capitalize()} ({variant})",
                         "body": " then ".join(s.replace("_", " ") for s in path) + "."})
    return rows


def _weighted(rng, weights: dict):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def build_accounts(rng, customers, usage):
    """The desk's accounts (larger ones more likely), each with its products,
    2-5 named contacts, and one recurring issue shaped by its products."""
    by_cust: dict[str, list[str]] = {}
    for u in usage:
        by_cust.setdefault(u["customer"], []).append(u["product"])
    size_w = {"SMB": 1, "Mid-market": 2, "Enterprise": 3}
    keyed = sorted(customers, key=lambda c: -rng.random() ** (1 / size_w[c["size"]]))
    accounts, contacts = [], []
    pcat = {p["product_id"]: p["category"] for p in nw.PRODUCTS}
    for c in keyed[:N_ACCOUNTS]:
        products = sorted(set(by_cust.get(c["customer_id"], []))) or [c["primary_product"]]
        us = [u for u in usage if u["customer"] == c["customer_id"]]
        adoption = sum(u["active"] == "yes" for u in us) / len(us) if us else 0.0
        mix: dict[str, float] = {}
        for p in products:
            for cat, w in PRODUCT_CAT[pcat[p]].items():
                mix[cat] = mix.get(cat, 0) + w
        rcat = _weighted(rng, mix)
        people = []
        for _ in range(rng.randint(2, 5)):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            cid = f"CON-{len(contacts) + 1:05d}"
            row = {"contact_id": cid, "email": f"{first.lower()}.{last.lower()}{len(contacts) % 7 or ''}@{domain_of(c)}",
                   "name": f"{first} {last}", "role": rng.choice(ROLES), "customer": c["customer_id"]}
            contacts.append(row)
            people.append(row)
        accounts.append({"c": c, "products": products, "contacts": people, "adoption": adoption,
                         "adoption_band": "high" if adoption >= 0.67 else ("low" if adoption < 0.34 else "medium"),
                         "recurring": (rcat, rng.choice(list(TOPICS[rcat])))})
    return accounts, contacts


def build_tickets(rng, accounts, kb, control_leak: float = 0.0):
    """`control_leak` plants a channel effect on detractor risk. It is 0 for the
    fixture; the test sets it to prove the control check can fail."""
    kb_by_res: dict[str, list[str]] = {}
    for a in kb:
        kb_by_res.setdefault(a["resolution"], []).append(a["article_id"])
    pcat = {p["product_id"]: p["category"] for p in nw.PRODUCTS}
    pname = {p["product_id"]: p["name"] for p in nw.PRODUCTS}
    size_w = {"SMB": 1, "Mid-market": 2, "Enterprise": 3}
    acc_w = [size_w[a["c"]["size"]] for a in accounts]

    days = (END - START).days
    stamps = sorted(START + timedelta(days=rng.randrange(days + 1)) for _ in range(N_TICKETS))
    last_issue: dict[tuple[str, str], date] = {}
    tickets, steps = [], []
    for i, day in enumerate(stamps):
        acc = rng.choices(accounts, weights=acc_w)[0]
        c = acc["c"]
        new_contact = rng.random() < 0.08
        person = None if new_contact else rng.choice(acc["contacts"])
        role = person["role"] if person else rng.choice(ROLES)
        product = rng.choice(acc["products"])

        if rng.random() < 0.30:
            cat, issue = acc["recurring"]
        else:
            w = {k: ROLE_CAT[role][k] * PRODUCT_CAT[pcat[product]][k] for k in CATS}
            cat = _weighted(rng, w)
            issue = rng.choice(list(TOPICS[cat]))
        res, phrases = TOPICS[cat][issue]
        if issue == "login" and day >= DRIFT_DATE and rng.random() < 0.8:
            res = "sso_reconnect"  # the planted drift: an SSO rollout changes the fix

        urgent = rng.random() < 0.15
        phrase = rng.choice(phrases)
        if "{product}" not in phrase and rng.random() < 0.6:
            phrase = "{product}: " + phrase
        parts = [rng.choice(OPENERS), phrase.format(product=pname[product])]
        if rng.random() < 0.10:  # a second topic in the same ticket: ambiguity
            ocat = rng.choice([k for k in TOPICS if k != cat])
            parts.append("also " + rng.choice(rng.choice(list(TOPICS[ocat].values()))[1]).format(product=pname[product]))
        if urgent:
            parts.append(rng.choice(URGENT))
        parts.append(rng.choice(CLOSERS))
        text = " ".join(p for p in parts if p).replace("  ", " ")

        # priority: a desk's triage rules, applied with some slack (10%): urgency
        # words or a bug on an Enterprise plan's SLA are high; how-to questions low
        rule = "high" if urgent or (cat == "bug" and c["plan"] == "Enterprise") else \
            ("low" if cat == "how_to" else "normal")
        priority = rule if rng.random() < 0.9 else rng.choice([p for p in ("high", "normal", "low") if p != rule])

        channel = rng.choice(CHANNELS)
        frt = rng.choices(FIRST_RESPONSE, weights=[3, 4, 3, 2] if priority != "high" else [5, 4, 2, 1])[0]
        key = (c["customer_id"], issue)
        repeat = key in last_issue and (day - last_issue[key]).days <= 30  # the SAME issue back again
        last_issue[key] = day
        sender = person["email"] if person else \
            f"{rng.choice(FIRST).lower()}.{rng.choice(LAST).lower()}.new@{domain_of(c)}"

        # outcome: detractor risk (channel deliberately absent: the control)
        recovery = rng.choice(RECOVERY)
        d = 0.12 + (0.20 if repeat else 0) + {">24h": 0.14, "4-24h": 0.05}.get(frt, 0) \
            + {"Red": 0.15, "Yellow": 0.05}.get(c["health"], 0) + _RECOVERY_EFFECT[c["size"]][recovery] \
            + (control_leak if channel == "chat" else 0.0)
        d = min(0.9, max(0.02, d))
        r = rng.random()
        nps_after = "detractor" if r < d else ("promoter" if r > d + 0.35 else "passive")
        csat = "bad" if nps_after == "detractor" and rng.random() < 0.7 else ("good" if nps_after == "promoter" or rng.random() < 0.5 else "neutral")

        offered = c["churned"] == "no" and rng.random() < 0.30
        accepted = None
        if offered:
            pa = 0.05 + 0.30 * acc["adoption"] + {"Free": 0.12, "Starter": 0.08}.get(c["plan"], 0)
            if c["health"] == "Red":
                pa = 0.02
            accepted = "yes" if rng.random() < pa else "no"

        tid = f"SUP-{i + 1:05d}"
        created = datetime.combine(day, datetime.min.time()) + timedelta(minutes=rng.randrange(8 * 60, 18 * 60))
        tickets.append({
            "ticket_id": tid, "created_at": created.isoformat(timespec="minutes"), "month": day.strftime("%Y-%m"),
            "text": text, "issue": issue, "adoption_band": acc["adoption_band"],
            "sender": sender, "sender_domain": sender.split("@")[1], "contact": person["contact_id"] if person else None,
            "channel": channel, "customer": c["customer_id"], "product": product,
            "category": cat, "priority": priority, "resolution": res,
            "kb_article": rng.choice(kb_by_res[res]) if rng.random() < 0.85 else None,
            "first_response": frt, "repeat_30d": "yes" if repeat else "no",
            "recovery": recovery, "nps_after": nps_after, "csat_band": csat,
            "upsell_offered": "yes" if offered else "no", "upsell_accepted": accepted,
        })

        path, t, prev, n = PATHS[res] + ["done"], created, "start", 0
        for step in path:
            seq = [rng.choice(DETOURS), step] if step != "done" and rng.random() < 0.15 else [step]
            for action in seq:
                n += 1
                t += timedelta(minutes=rng.randrange(5, 240))
                steps.append({"step_id": f"{tid}-{n}", "ticket": tid, "step_no": n, "category": cat,
                              "previous_action": prev, "action": action, "created_at": t.isoformat(timespec="minutes")})
                prev = action
    return tickets, steps


def split_incoming(tickets, steps):
    """Hold out the newest HOLDOUT tickets (and their steps) as the incoming queue.
    They are never loaded into Aito, so the envelope view predicts on tickets Aito
    has not seen, and can compare against their recorded truth honestly."""
    # by the exact stamp: tickets are generated in day order, but with random times in a day
    held = {t["ticket_id"] for t in sorted(tickets, key=lambda t: (t["created_at"], t["ticket_id"]))[-HOLDOUT:]}
    return ([t for t in tickets if t["ticket_id"] not in held], [s for s in steps if s["ticket"] not in held],
            {"tickets": [t for t in tickets if t["ticket_id"] in held],
             "steps": [s for s in steps if s["ticket"] in held]})


def generate(control_leak: float = 0.0):
    customers, usage = northwind()
    rng = random.Random(SEED)
    accounts, contacts = build_accounts(rng, customers, usage)
    kb = build_kb()
    tickets, steps = build_tickets(rng, accounts, kb, control_leak)
    return kb, contacts, tickets, steps


def main(out: Path = OUT, incoming: Path = INCOMING) -> None:
    kb, contacts, tickets, steps = generate()
    tickets, steps, held = split_incoming(tickets, steps)
    out.mkdir(exist_ok=True)
    for name, rows in (("kb_articles", kb), ("support_contacts", contacts),
                       ("support_tickets", tickets), ("support_steps", steps)):
        (out / f"{name}.json").write_text(json.dumps(rows, indent=0, sort_keys=True) + "\n")
        print(f"{name}: {len(rows)} rows")
    incoming.parent.mkdir(exist_ok=True)
    incoming.write_text(json.dumps(held, indent=0, sort_keys=True) + "\n")
    print(f"incoming (held out, not loaded): {len(held['tickets'])} tickets -> {incoming}")


if __name__ == "__main__":
    main()
