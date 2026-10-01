"""The confidence gates, one place for the whole app (frontend/lib/gates.ts mirrors
them; tests/test_confidence_display.py checks they agree).

At or above AUTO_GATE Aito's answer is served as is; below ASSIST_GATE a person
decides; in between the LLM gets Aito's shortlist.
"""

AUTO_GATE = 0.85
ASSIST_GATE = 0.65
