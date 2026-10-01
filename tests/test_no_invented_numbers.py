"""Numbers on screen are measured or computed live, never written into the copy
(2026-09-30 sanity check, item e)."""

import re
from pathlib import Path

from src import app as A

FRONT = Path(__file__).resolve().parents[1] / "frontend" / "components"


class _Outreach:
    _ver = "v2"

    def __init__(self, hits=True):
        self.hits, self.predicted = hits, []

    def recommend(self, table, where, field, goal, limit=5):
        if not self.hits:
            return {"hits": []}
        return {"hits": [{"feature": {"channel": "Referral", "angle": "ROI", "personalization": "Medium"}[field], "$p": 0.4}]}

    def predict(self, table, where, target, limit=5, select=None):
        self.predicted.append(dict(where))
        return {"hits": [{"feature": "yes", "$p": 0.3}, {"feature": "no", "$p": 0.7}]}


def test_the_outreach_projection_uses_only_what_aito_recommended(monkeypatch):
    fake = _Outreach()
    monkeypatch.setattr(A, "aito", fake)
    r = A._tool_recommend_outreach({"target_industry": "Retail", "target_role": "CFO"})
    assert (r["channel"], r["angle"], r["personalization"]) == ("Referral", "ROI", "Medium")
    proj = [w for w in fake.predicted if "channel" in w]
    assert proj and not {"subject_style", "send_day"} & set(proj[0])        # no hard-coded extras
    assert proj[0]["personalization"] == "Medium"                            # Aito's pick, not "High"


def test_no_recommendation_means_none_not_a_made_up_play(monkeypatch):
    monkeypatch.setattr(A, "aito", _Outreach(hits=False))
    r = A._tool_recommend_outreach({"target_industry": "Retail", "target_role": "CFO"})
    assert r["channel"] is None and r["angle"] is None and r["meeting_probability"] is None


def test_the_handoff_caveat_example_is_measured_live(monkeypatch):
    class _P:
        def predict(self, table, where, target, limit=5, select=None):
            return {"hits": [{"feature": "cancel_service", "$p": 0.61}, {"feature": "refund", "$p": 0.2}]}
    monkeypatch.setattr(A, "aito", _P())
    ex = A.handoff()["caveat_example"]
    assert ex["text"] == A._CAVEAT_EXAMPLE and (ex["intent"], ex["p"]) == ("cancel_service", 0.61)


def test_static_code_panes_state_no_results():
    """The side panels' example queries are illustrations: they may name a query, not claim its result."""
    src = (FRONT / "AppShell.tsx").read_text()
    panes = re.findall(r'code: "((?:[^"\\]|\\.)*)"', src)
    claims = [p for p in panes if re.search(r"\d+%\s*→\s*\d+%", p)]
    assert not claims, claims


def test_copy_numbers_have_a_source():
    for f, needle in (("HandoffView.tsx", "at 91%"), ("OverviewView.tsx", "3.6 s"), ("OverviewView.tsx", "about 22 s")):
        assert needle not in (FRONT / f).read_text(), f"{f}: '{needle}' has no results file behind it"
