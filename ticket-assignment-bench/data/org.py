"""The support organisation: customers, product areas, projects, and the rule
that maps a ticket to its correct assignee.

Key property (this is the whole point): the assignee depends on the STRUCTURED
fields — `customer`, the product area implied by the text, and `project` for
shared areas — NOT on surface text alone. Two customers with the identical
symptom text have DIFFERENT correct assignees. So inferring the assignee from
text-similar neighbours (ignoring customer) is structurally wrong.
"""

from __future__ import annotations

import random

from bench import config

CUSTOMERS = ["acme", "globex", "initech", "umbrella", "soylent", "hooli", "vehement", "stark"]
PRODUCT_AREAS = ["network", "billing", "identity", "hardware", "software", "cloud"]
PROJECTS = ["alpha", "beta"]
PRIORITIES = ["low", "medium", "high"]

# Surface forms the customer name takes when it leaks into ticket text — the
# multi-source reality (human emails, portal, aliases). Used by v2.1 to model
# "the customer name was often in the title or body" yet naive search still
# misbehaves (embedding dilution).
CUSTOMER_ALIASES = {
    "acme": ["Acme", "Acme Corp", "ACME"],
    "globex": ["Globex", "Globex Inc", "globex"],
    "initech": ["Initech", "Initech LLC"],
    "umbrella": ["Umbrella", "Umbrella Corp", "UmbrellaCo"],
    "soylent": ["Soylent", "Soylent Industries"],
    "hooli": ["Hooli", "Hooli Inc"],
    "vehement": ["Vehement", "Vehement Capital"],
    "stark": ["Stark", "Stark Industries", "Stark Ind"],
}
SOURCES = ["email", "portal", "automation"]   # automation tickets carry no customer name

# v3: customer/project are NOT fields — they must be inferred. The real signal is
# the email SENDER DOMAIN, which usually (not always) identifies the customer.
CUSTOMER_DOMAINS = {
    "acme": "acmecorp.com", "globex": "globex.io", "initech": "initech.com",
    "umbrella": "umbrella-corp.com", "soylent": "soylent.co", "hooli": "hooli.com",
    "vehement": "vehementcapital.com", "stark": "starkindustries.com",
}
FREEMAIL_DOMAINS = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com"]
PORTAL_DOMAIN = "tickets.helpdesk.io"        # portal-sourced: no customer in the address
AUTOMATION_DOMAIN = "alerts.monitoring.io"   # automation: no customer in the address
DOMAIN_TO_CUSTOMER = {d: c for c, d in CUSTOMER_DOMAINS.items()}

# A subset of (customer, area) pairs are "shared": two agents split by project.
# This creates genuine within-customer ambiguity that text+customer retrieval
# cannot resolve but conditioning on `project` (Aito) can.
def _shared_pairs() -> set[tuple[str, str]]:
    rng = random.Random(config.SEED ^ 0x54ED)
    pairs = [(c, a) for c in CUSTOMERS for a in PRODUCT_AREAS]
    rng.shuffle(pairs)
    n_shared = round(0.3 * len(pairs))
    return set(pairs[:n_shared])


SHARED = _shared_pairs()


def assignee_for(customer: str, area: str, project: str) -> str:
    """Deterministic ground-truth assignment. v3 focuses on customer inference
    from the sender, so it uses one agent per (customer, area); the project-split
    washout was characterised in v2.1."""
    return f"{customer}-{area}-a"


def all_agents() -> list[str]:
    agents = set()
    for c in CUSTOMERS:
        for a in PRODUCT_AREAS:
            for p in PROJECTS:
                agents.add(assignee_for(c, a, p))
    return sorted(agents)


if __name__ == "__main__":
    ags = all_agents()
    print(f"{len(CUSTOMERS)} customers × {len(PRODUCT_AREAS)} areas, "
          f"{len(SHARED)} shared pairs -> {len(ags)} distinct agents")
