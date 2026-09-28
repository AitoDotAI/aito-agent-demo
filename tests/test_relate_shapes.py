"""/company drivers read _relate hits in every encoding (the ecommerce demo's
parsers accepted only v1's `$has` and silently showed no drivers on v2).

v1 wraps a proposition in an operator, v2 states it bare, and conjunctions
come as `$and` (v1) or `$group` (v2). All must yield the same drivers. Runs on
fabricated hits in the live shapes, so it needs no Aito.
"""

import pytest

from src import app as app_module

PS = {"pOnCondition": 0.44, "pOnNotCondition": 0.17}
SHAPES = {
    "v1 $has": {"health": {"$has": "Red"}},
    "v2 bare": {"health": "Red"},
    "v1 $and": {"$and": [{"health": {"$has": "Red"}}]},
    "v2 $group": {"$group": [{"health": "Red"}]},
}


@pytest.mark.parametrize("shape", SHAPES)
def test_why_props_reads_every_encoding(shape):
    assert list(app_module._why_props(SHAPES[shape])) == [("health", "Red")]


def test_a_conjunction_yields_each_member():
    for prop in ({"$and": [{"health": {"$has": "Red"}}, {"plan": {"$has": "Free"}}]},
                 {"$group": [{"health": "Red"}, {"plan": "Free"}]}):
        assert list(app_module._why_props(prop)) == [("health", "Red"), ("plan", "Free")]


class _FakeAito:
    def __init__(self, prop):
        self.hits = [{"lift": 1.86, "ps": PS, "related": prop, "condition": prop}]

    def relate(self, table, target, fields):
        return {"hits": self.hits}

    def relate_on(self, table, target, on):
        return {"hits": self.hits}


@pytest.mark.parametrize("scoped", [False, True], ids=["global", "$on"])
@pytest.mark.parametrize("shape", SHAPES)
def test_relate_drivers_are_the_same_in_every_encoding(monkeypatch, shape, scoped):
    monkeypatch.setattr(app_module, "aito", _FakeAito(SHAPES[shape]))
    seg = [{"size": "SMB"}] if scoped else []
    drivers = app_module._relate_drivers("customers", "churned", "yes", seg, set(), ["health"])
    assert [(d["field"], d["value"], d["lift"]) for d in drivers] == [("health", "Red", 1.86)]
