"""Measure the handoff tier on its probe set: which tier each text lands in, and why.

The 18 probes are the handoff queue's own 10 tickets (3 written to be unsure,
7 clear) plus 8 vague or off-topic texts. Each has the tier it should get. Prints
a table with Aito's $p, the demo's word-coverage check and the resulting tier, so
the same run re-measures when Aito's own coverage signal replaces the check.

    AITO_API_VERSION=v2 uv run python scripts/handoff_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import app as A  # noqa: E402

#: (text, the tier it should get). "handoff" for the clear refund/cancel tickets is
#: the sensitive-action rule: confident, but a person verifies money and state changes.
PROBES = [
    ("Is there a network outage? Nothing works in Helsinki.", "auto"),
    ("My screen is cracked, the glass is shattered.", "auto"),
    ("What's my current account balance?", "auto"),
    ("Where's your nearest shop in Tampere?", "auto"),
    ("My battery dies within an hour now.", "auto"),
    ("Please cancel my home internet, I'm moving abroad.", "handoff"),
    ("Hi, please refund the €45 charge on my roaming pack.", "handoff"),
    ("Nothing has worked properly since last week and I want real answers.", "handoff"),
    ("I am not sure, can someone just call me back", "handoff"),
    ("I have a few different problems with my account and nobody is helping me", "handoff"),
    ("hello?", "handoff"),
    ("asdf qwerty", "handoff"),
    ("I'm not happy", "handoff"),
    ("I want to talk to a human", "handoff"),
    ("Can you help me with something", "handoff"),
    ("What's the weather like in Oulu tomorrow?", "handoff"),
    ("My dog ate my SIM card lol", "handoff"),
    ("Same problem as last time", "handoff"),
]


def tier(text: str, guard: bool) -> tuple[str, float, str, float]:
    """The tier and why, in the same order as /api/handoff decides it."""
    intent, p, _ = A._top_and_alts(A.aito.predict("resolutions", {"text": text}, "intent", limit=3,
                                                   select=["$p", "feature"]))
    cov = A._coverage(text)
    if guard and cov < A._COVERAGE_GATE:
        band = "handoff (unfamiliar)"
    elif p < A._ASSIST_GATE:
        band = "handoff (low $p)"
    elif intent in A._SENSITIVE:
        band = "handoff (sensitive)"
    else:
        band = "auto" if p >= A._AUTO_GATE else "assist"
    return band, p, intent, cov


def main() -> None:
    print(f"engine {A.aito._request('GET', A.aito._path('_version')).get('version')}, "
          f"coverage gate {A._COVERAGE_GATE}")
    print("| text | expected | $p (intent) | coverage | without the check | with it |")
    print("|---|---|---|---|---|---|")
    ok_before = ok_after = 0
    for text, want in PROBES:
        before, p, intent, cov = tier(text, guard=False)
        after, *_ = tier(text, guard=True)
        ok_before += before.split()[0] == want
        ok_after += after.split()[0] == want
        mark = lambda b: b + ("" if b.split()[0] == want else " ✗")  # noqa: E731
        print(f"| {text} | {want} | {p:.2f} ({intent}) | {cov:.2f} | {mark(before)} | {mark(after)} |")
    print(f"\nright tier: {ok_before}/{len(PROBES)} without the check, {ok_after}/{len(PROBES)} with it")


if __name__ == "__main__":
    main()
