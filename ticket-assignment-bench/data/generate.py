"""Generate the labelled ticket pool and the fixed TEST/VAL splits.

    python -m data.generate

Writes data/pool_train.json (the TRAIN pool the scaling sweep draws nested
prefixes from), data/val.json, data/test.json. Texts deliberately REPEAT across
customers — that recurrence is the cross-customer collision the benchmark is
about — so we assert id-uniqueness and split-disjointness, NOT text-uniqueness.
"""

from __future__ import annotations

import json
import random

from bench import config
from data.org import (
    AUTOMATION_DOMAIN, CUSTOMER_ALIASES, CUSTOMER_DOMAINS, CUSTOMERS, FREEMAIL_DOMAINS,
    PORTAL_DOMAIN, PRIORITIES, PRODUCT_AREAS, PROJECTS, SOURCES,
    all_agents, assignee_for,
)
from data.text import inject_customer, make_text


def _sender_domain(customer: str, source: str, rng: random.Random) -> str:
    """The sender domain that ticket arrives from. Email usually reveals the
    customer (their corporate domain) but sometimes a freemail address; portal
    and automation never carry the customer."""
    if source == "email":
        return rng.choices(
            [CUSTOMER_DOMAINS[customer], rng.choice(FREEMAIL_DOMAINS)],
            weights=[0.7, 0.3],
        )[0]
    if source == "portal":
        return PORTAL_DOMAIN
    return AUTOMATION_DOMAIN


def build_pool() -> list[dict]:
    rng = random.Random(config.TEXT_SEED)
    n = config.POOL_SIZE + config.TEST_SIZE + 400  # pool + test + val
    rows = []
    ids = rng.sample(range(100000, 100000 + n * 4), n)
    for i in range(n):
        customer = rng.choice(CUSTOMERS)
        area = rng.choice(PRODUCT_AREAS)
        project = rng.choice(PROJECTS)
        priority = rng.choice(PRIORITIES)
        source = rng.choices(SOURCES, weights=[0.5, 0.3, 0.2])[0]

        text = make_text(area, rng)
        # v2.1: leak the customer name into the text the way each source does.
        # email tickets usually name the customer; portal sometimes; automation never.
        if source == "email":
            where = rng.choices(["prefix", "body", "none"], weights=[0.6, 0.2, 0.2])[0]
        elif source == "portal":
            where = rng.choices(["body", "prefix", "none"], weights=[0.35, 0.15, 0.5])[0]
        else:  # automation
            where = "none"
        if where != "none":
            text = inject_customer(text, rng.choice(CUSTOMER_ALIASES[customer]), where)

        rows.append({
            "id": f"AS-{ids[i]}",
            "text": text,
            "customer": customer,        # LATENT — never provided at query time in v3
            "product_area": area,        # ground-truth area (analysis only)
            "project": project,
            "priority": priority,
            "source": source,
            "sender_domain": _sender_domain(customer, source, rng),
            "assignee": assignee_for(customer, area, project),
        })
    return rows


def split(rows: list[dict]) -> dict[str, list[dict]]:
    rng = random.Random(config.SAMPLE_SEED)
    rows = rows[:]
    rng.shuffle(rows)
    test = rows[: config.TEST_SIZE]
    val = rows[config.TEST_SIZE: config.TEST_SIZE + 400]
    train_pool = rows[config.TEST_SIZE + 400:]
    return {"test": test, "val": val, "pool_train": train_pool}


def _validate(splits: dict[str, list[dict]]) -> None:
    idsets = {k: {r["id"] for r in v} for k, v in splits.items()}
    assert idsets["test"].isdisjoint(idsets["val"])
    assert idsets["test"].isdisjoint(idsets["pool_train"])
    assert idsets["val"].isdisjoint(idsets["pool_train"])
    assert len(splits["pool_train"]) >= max(config.TRAIN_SIZES), "pool too small for sweep"
    # the largest train prefix must cover every agent, else some labels are unpredictable
    big = splits["pool_train"][: max(config.TRAIN_SIZES)]
    covered = {r["assignee"] for r in big}
    missing = set(all_agents()) - covered
    assert not missing, f"agents missing from largest TRAIN: {sorted(missing)[:5]}..."


def main() -> None:
    pool = build_pool()
    splits = split(pool)
    _validate(splits)
    for name, data in splits.items():
        (config.DATA_DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False))
        print(f"wrote {name}.json: {len(data)} rows")
    from collections import Counter
    from data.org import CUSTOMER_DOMAINS
    test = splits["test"]
    def _named(r):
        return any(a.lower() in r["text"].lower() for a in CUSTOMER_ALIASES[r["customer"]])
    sender_reveals = sum(r["sender_domain"] == CUSTOMER_DOMAINS[r["customer"]] for r in test) / len(test)
    print("agents:", len(all_agents()))
    print("test sources:", dict(Counter(r["source"] for r in test)))
    print("customer name in text:", round(sum(_named(r) for r in test) / len(test), 2))
    print("sender domain reveals customer:", round(sender_reveals, 2))


if __name__ == "__main__":
    main()
