"""Booktest for the resolution scorecard (../resolution-scorecard).

Tracks the bench's behaviour as a snapshot: it generates the seeded dataset,
uploads a small TRAIN slice to Aito, and books Aito's `_predict` resolutions
(intent + the parameter that intent needs) on a fixed sample.

`@bt.snapshot_httpx()` records every Aito HTTP call on the first run (live) and
replays them afterwards — so this stays fast, free and deterministic, and any
drift in the bench's resolution behaviour shows up as a snapshot diff.

    ./do test-book                              # run / replay (no live calls)
    ./do test-book -s -a book/test_02_*.py      # re-record against live Aito + accept

First record needs AITO creds in .env and (re)creates the synthetic
`resolutions` table.
"""

import pathlib
import random
import sys
from collections import Counter

import booktest as bt

SCORECARD = pathlib.Path(__file__).resolve().parent.parent / "resolution-scorecard"

# one clear ticket per intent (fixed → stable requests → stable snapshot)
SAMPLE = [
    ("Please cancel my broadband.", "acme.com", "cancel_service", "broadband"),
    ("I want a refund for my mobile plan charge.", "globex.com", "refund", "mobile_plan"),
    ("Is there an outage in Helsinki?", "tickets.helpdesk.io", "check_outage", "Helsinki"),
    ("Where is your nearest shop in Tampere?", "initech.com", "find_shop", "Tampere"),
    ("My screen is cracked, the glass is shattered.", "support", "repair_help", "cracked_screen"),
    ("What is my account balance?", "stark.com", "check_balance", None),
]


@bt.snapshot_httpx()
def test_resolution_scorecard(t: bt.TestCaseRun):
    sys.path.insert(0, str(SCORECARD))
    try:
        from aito.client import AitoClient
        from bench import config as C
        from data.generate import build
    finally:
        pass

    t.h1("Resolution scorecard — Aito resolutions")

    # --- deterministic dataset (no API) ---
    rng = random.Random(C.SEED)
    train = build(300, rng)
    t.h2("Seeded dataset slice (TRAIN = 300)")
    by_intent = Counter(r["intent"] for r in train)
    for intent in C.INTENTS:
        t.tln(f"- {intent}: {by_intent[intent]}")
    t.assertln("all intents present", set(by_intent) == set(C.INTENTS))

    # --- live Aito (recorded by snapshot_httpx) ---
    t.h2("Aito `_predict` on a fixed sample")
    t.tln(f"DB `{C.aito_url()}` · table `{C.AITO_TABLE}` · predict from {{text, sender_domain}}")
    t.tln("")

    intent_hits = 0
    param_hits = 0
    param_total = 0
    with AitoClient() as a:
        a.recreate_and_upload(train)
        for text, sender, gold_intent, gold_param in SAMPLE:
            where = {"text": text, "sender_domain": sender}
            pi = a.predict("intent", where)
            intent_ok = pi.feature == gold_intent
            intent_hits += intent_ok
            line = f"- “{text}” → intent **{pi.feature}**"
            pf = C.INTENT_PARAM.get(pi.feature)
            if pf:
                pp = a.predict(pf, where)
                line += f", {pf} **{pp.feature}**"
                if gold_param is not None:
                    param_total += 1
                    param_hits += pp.feature == gold_param
            t.tln(line + (f"   _(gold: {gold_intent}/{gold_param})_" if not intent_ok else ""))
            t.iln(f"    p(intent)={pi.p:.2f}")

    t.h2("Summary")
    t.tln(f"- intent accuracy on sample: {intent_hits}/{len(SAMPLE)}")
    t.tln(f"- parameter accuracy on sample: {param_hits}/{param_total}")
    t.assertln("intent prediction is reliable on clear tickets", intent_hits >= len(SAMPLE) - 1)
