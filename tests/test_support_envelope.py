"""The support envelope enforces the fixture's inputs-vs-targets table in code.

Every "do not use" pair in scripts/support_fixture/README.md must refuse, and a
full envelope run must never hand a prediction a field that is recorded after
the ticket or gives its target away. Runs on a fake client, so it needs no Aito."""

import pytest
from fastapi.testclient import TestClient

from src import app as app_module
from src import support_envelope as env
from src.support_envelope import LeakError, check_inputs

T = "support_tickets"

# (target table, target, the forbidden inputs), straight from the README table
README_FORBIDDEN = [
    (T, "category", ["resolution", "kb_article", "kb_article.resolution"]),
    (T, "resolution", ["resolution", "kb_article", "kb_article.resolution"]),
    (T, "priority", ["first_response"]),
    (T, "nps_after", ["csat_band"]),
    ("support_steps", "action", ["ticket.resolution", "ticket.kb_article"]),
]


@pytest.mark.parametrize("table,target,fields", README_FORBIDDEN)
def test_every_readme_leak_refuses(table, target, fields):
    for f in fields:
        with pytest.raises(LeakError):
            check_inputs(table, target, {"text": "x", f: "anything"} if table == T else {f: "x"})


def test_outcomes_and_later_fields_never_reach_intake_predictions():
    later = ["issue", "nps_after", "csat_band", "recovery", "upsell_offered", "upsell_accepted", "first_response"]
    for target in ("customer", "category", "resolution", "kb_article"):
        for f in later:
            with pytest.raises(LeakError):
                check_inputs(T, target, {"text": "x", f: "y"})


def test_upsell_is_only_predicted_where_an_offer_was_made():
    with pytest.raises(LeakError):
        check_inputs(T, "upsell_accepted", {"adoption_band": "high"})
    check_inputs(T, "upsell_accepted", {"adoption_band": "high", "upsell_offered": "yes"})


def test_allowed_inputs_pass_including_linked_attributes():
    check_inputs(T, "category", {"text": "x", "customer.plan": "Pro", "product.tier": "Core", "month": "2026-09"})
    check_inputs(T, "priority", {"text": "x", "category": "bug"})
    check_inputs("support_steps", "action", {"previous_action": "start", "ticket.issue": "login",
                                             "ticket.customer.size": "SMB"})
    with pytest.raises(LeakError):  # a link that isn't on the list stays closed
        check_inputs(T, "category", {"kb_article.title": "x"})
    with pytest.raises(LeakError):  # a target nobody listed
        check_inputs(T, "channel", {"text": "x"})


def test_recommend_checks_the_recommended_field_too():
    fake = _Fake()
    with pytest.raises(LeakError):  # csat_band is not an input nps_after may use
        env.guarded_recommend(fake, T, {"customer": "c"}, "csat_band", {"nps_after": "promoter"})
    env.guarded_recommend(fake, T, {"customer": "c"}, "recovery", {"nps_after": "promoter"})


class _Fake:
    def __init__(self):
        self.calls = []

    def predict(self, table, where, target, limit=5, select=None):
        self.calls.append(("predict", table, dict(where), target))
        return {"hits": [{"feature": "v1", "$p": 0.9}, {"feature": "v2", "$p": 0.05}]}

    def recommend(self, table, where, field, goal, limit=5):
        self.calls.append(("recommend", table, dict(where), field))
        return {"hits": [{"feature": "apology_credit", "$p": 0.4}]}

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        self.calls.append(("query", table, where, order_by))
        return {"hits": [{"ticket_id": "SUP-1", "text": "t", "resolution": "refund", "nps_after": "passive"}]}

    def get_schema(self):
        return {"schema": {"support_tickets": {}, "support_steps": {}, "customers": {}}}


TRUTH_ONLY = {"resolution", "kb_article", "issue", "nps_after", "csat_band", "first_response",
              "recovery", "upsell_accepted", "ticket.resolution", "ticket.kb_article"}


def test_a_full_run_never_feeds_a_prediction_a_truth_only_field():
    q = env.load_incoming()
    for tid in q["order"][:25]:
        fake = _Fake()
        out = env.envelope(fake, q["tickets"][tid], q["steps"].get(tid, []))
        for kind, table, where, _ in fake.calls:
            if kind != "query":
                assert not TRUTH_ONLY & set(where), (tid, kind, where)
        assert [s["key"] for s in out["steps"]] == [
            "customer", "category", "priority", "resolution", "kb", "similar", "first_step", "risk", "recovery", "upsell"]
        assert out["gate"] == "auto"  # the fake is 0.9 sure; AUTO is 0.85


def test_routes_say_not_loaded_and_unknown(monkeypatch):
    c = TestClient(app_module.app)
    monkeypatch.setitem(app_module._support_state, "checked", 1e18)  # skip the live schema check
    monkeypatch.setitem(app_module._support_state, "loaded", False)
    tid = env.load_incoming()["order"][0]
    assert c.get("/api/support/envelope", params={"ticket_id": tid}).status_code == 503
    assert c.get("/api/support/envelope", params={"ticket_id": "SUP-nope"}).status_code == 404
    monkeypatch.setitem(app_module._support_state, "loaded", True)
    monkeypatch.setattr(app_module, "_support_aito", _Fake())
    r = c.get("/api/support/envelope", params={"ticket_id": tid})
    assert r.status_code == 200 and r.json()["aito_calls"] == 10
