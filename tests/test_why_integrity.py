"""The `$why`-belongs-to-its-row invariant (org/demo-why-integrity-audit.md).

An explanation rendered next to a value must be that value's own `$why`: the
`baseP` proposition inside it names the value it explains. These run on
fabricated `_predict` responses in the live shape, so they need no Aito.
"""

import pytest

from src import app as app_module
from src.aito_client import AitoError


def _why(outcome, lift_field, lift_value, lift):
    return {"type": "product", "factors": [
        {"type": "baseP", "value": 0.5, "proposition": {"outcome": {"$has": outcome}}},
        {"type": "relatedPropositionLift", "value": lift,
         "proposition": {lift_field: {"$has": lift_value}}},
    ]}


# A losing deal: `lost` ranks first, so hits[0] is NOT the value on screen.
LOSING_DEAL = {"hits": [
    {"feature": "lost", "$p": 0.59, "$why": _why("lost", "relationship", "New logo", 1.12)},
    {"feature": "won", "$p": 0.41, "$why": _why("won", "relationship", "New logo", 0.92)},
]}


def test_why_target_reads_the_baseP_proposition():
    assert app_module._why_target(_why("won", "x", "y", 1.0)) == "won"
    # v2 may state a proposition as a bare value
    bare = {"type": "product", "factors": [{"type": "baseP", "value": 0.5,
                                            "proposition": {"outcome": "won"}}]}
    assert app_module._why_target(bare) == "won"
    assert app_module._why_target(None) is None


def test_why_of_takes_the_explanation_of_the_value_shown_not_hits0():
    why = app_module._why_of(LOSING_DEAL["hits"], "won")
    assert app_module._why_target(why) == "won"


def test_why_of_refuses_an_explanation_of_another_value():
    swapped = [{"feature": "won", "$p": 0.41, "$why": _why("lost", "a", "b", 1.5)}]
    with pytest.raises(AitoError, match="rendered under 'won'"):
        app_module._why_of(swapped, "won")


def test_why_of_matches_boolean_targets():
    hits = [{"feature": True, "$p": 0.9, "$why": {"type": "product", "factors": [
        {"type": "baseP", "value": 0.5, "proposition": {"meeting": {"$has": True}}}]}}]
    assert app_module._why_of(hits, True) is hits[0]["$why"]


def test_win_odds_drivers_explain_winning_even_when_losing_ranks_first(monkeypatch):
    # The live bug, 2026-09-26: at win odds 0.41 the drivers shown under
    # "win" were hits[0]'s, i.e. the drivers of LOSING (New logo x1.12,
    # where the same attribute is x0.92 against winning).
    monkeypatch.setattr(app_module.aito, "predict", lambda *a, **k: LOSING_DEAL)

    out = app_module._tool_win_odds({"industry": "Retail"})

    assert out["win_probability"] == 0.41
    assert out["drivers"] == [{"field": "relationship", "value": "New logo", "lift": 0.92}]
