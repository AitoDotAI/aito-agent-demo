"""The confidence gates, one place for the whole app (frontend/lib/gates.ts mirrors
the two constants; tests/test_confidence_display.py checks they agree).

At or above AUTO_GATE Aito's answer is served as is; below ASSIST_GATE a person
decides; in between the LLM gets Aito's shortlist.

`band_of` and `margin_to_gate` live here for the same reason the constants do.
The band — not the predicted label — is what a visitor sees happen, and it is
decided in two places that must not drift apart: /api/handoff (src/app.py) and
the live gate that checks the deployed site (scripts/live_smoke.py). Keep this
module import-free so the gate script can import it without the app's deps.
"""

AUTO_GATE = 0.85
ASSIST_GATE = 0.65


def band_of(p: float, sensitive: bool = False) -> str:
    """Which of the three things a visitor sees happen to a $p.

    `auto` is served as is, `assist` goes to the LLM with Aito's shortlist,
    `handoff` is left to a person. Unsure is tested first — Aito won't guess on
    a low confidence whatever the intent is — then sensitive (money or a state
    change always gets human eyes), then the auto gate.
    """
    if p < ASSIST_GATE:
        return "handoff"
    if sensitive:
        return "handoff"
    return "auto" if p >= AUTO_GATE else "assist"


def margin_to_gate(p: float) -> tuple[str, float]:
    """The gate that decides this $p's band, and the signed distance to it.

    Reported so a band about to flip is visible BEFORE it flips: a $p a
    thousandth above AUTO_GATE serves `auto` today and `assist` after any
    drift, while every predicted label in the response stays identical.
    """
    gate = AUTO_GATE if abs(p - AUTO_GATE) <= abs(p - ASSIST_GATE) else ASSIST_GATE
    return ("auto" if gate == AUTO_GATE else "assist"), p - gate
