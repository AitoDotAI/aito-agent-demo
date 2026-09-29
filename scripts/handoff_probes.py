"""Measure the handoff tier on its probe set: which tier each text lands in, and why.

The 18 probes are the handoff queue's own 10 tickets (3 written to be unsure,
7 clear) plus 8 vague or off-topic texts. Each has the tier it should get. Prints
a table with Aito's $p and the resulting tier, so the same run re-measures the day
Aito's evidence-coverage fix (td-20260929104053883876) is on shared. The fixed,
untuned benchmark for that fix is the held-out set in
~/.tmp/handoff-coverage-probe/heldout_probes.json.

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


def tier(text: str) -> tuple[str, float, str]:
    """The tier and why, in the same order as /api/handoff decides it."""
    intent, p, _ = A._top_and_alts(A.aito.predict("resolutions", {"text": text}, "intent", limit=3,
                                                   select=["$p", "feature"]))
    if p < A._ASSIST_GATE:
        band = "handoff (low $p)"
    elif intent in A._SENSITIVE:
        band = "handoff (sensitive)"
    else:
        band = "auto" if p >= A._AUTO_GATE else "assist"
    return band, p, intent


def main() -> None:
    print(f"engine {A.aito._request('GET', A.aito._path('_version')).get('version')}")
    print("| text | expected | $p (intent) | tier |")
    print("|---|---|---|---|")
    ok = 0
    for text, want in PROBES:
        band, p, intent = tier(text)
        ok += band.split()[0] == want
        print(f"| {text} | {want} | {p:.2f} ({intent}) | {band}{'' if band.split()[0] == want else ' ✗'} |")
    print(f"\nright tier: {ok}/{len(PROBES)}")


if __name__ == "__main__":
    main()
