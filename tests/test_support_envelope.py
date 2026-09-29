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
    for target in ("customer", "product", "category", "resolution", "kb_article"):
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
    for f in ("customer.churned", "customer.name_of_anything"):  # nor does an attribute that isn't
        with pytest.raises(LeakError):
            check_inputs(T, "category", {"text": "x", f: "yes"})
    with pytest.raises(LeakError):
        check_inputs("support_steps", "action", {"previous_action": "start", "ticket.customer.churned": "yes"})
    with pytest.raises(LeakError):  # a target nobody listed
        check_inputs(T, "channel", {"text": "x"})


def test_recommend_checks_the_recommended_field_too():
    fake = _Fake()
    with pytest.raises(LeakError):  # csat_band is not an input nps_after may use
        env.guarded_recommend(fake, T, {"customer": "c"}, "csat_band", {"nps_after": "promoter"})
    env.guarded_recommend(fake, T, {"customer": "c"}, "recovery", {"nps_after": "promoter"})


class _Fake:
    """Predicts "v1" at 0.9 for everything; knows the sender as a contact of ACC-FAKE
    unless `known=False`, so tests can tell a looked-up or predicted value from the truth."""

    def __init__(self, known=True):
        self.calls, self.known = [], known

    def predict(self, table, where, target, limit=5, select=None):
        self.calls.append(("predict", table, dict(where), target))
        return {"hits": [{"feature": "v1", "$p": 0.9}, {"feature": "v2", "$p": 0.05}]}

    def recommend(self, table, where, field, goal, limit=5):
        self.calls.append(("recommend", table, dict(where), field))
        return {"hits": [{"feature": "apology_credit", "$p": 0.4}]}

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        self.calls.append(("query", table, where, order_by))
        if table == "support_contacts":
            return {"hits": [{"contact_id": "CON-1", "name": "Anna Laine", "role": "finance",
                              "customer": "ACC-FAKE"}] if self.known else []}
        return {"hits": [{"ticket_id": "SUP-1", "text": "t", "resolution": "refund", "nps_after": "passive"}]}

    def get_schema(self):
        return {"schema": {"support_tickets": {}, "support_steps": {}, "customers": {}}}


# Never an input to any prediction in the envelope. (`ticket.issue` is allowed for a
# step once the issue is diagnosed, but the envelope's first step doesn't use it.)
TRUTH_ONLY = {"resolution", "kb_article", "issue", "nps_after", "csat_band", "first_response",
              "recovery", "upsell_accepted", "ticket.resolution", "ticket.kb_article", "ticket.issue",
              "customer.churned"}
KEYS = ["customer", "product", "category", "priority", "resolution", "kb", "similar", "first_step",
        "risk", "recovery", "upsell"]


def test_a_full_run_feeds_only_what_the_agent_would_know():
    q = env.load_incoming()
    for tid in q["order"]:
        t, fake = q["tickets"][tid], _Fake()
        out = env.envelope(fake, t, q["steps"].get(tid, []))
        for kind, table, where, target in fake.calls:
            if kind == "query":
                continue
            assert not TRUTH_ONLY & set(where), (tid, kind, where)
            # the looked-up account and the PREDICTED product, category and priority go
            # downstream ("ACC-FAKE" / "v1" from the fake), never the ticket's truth
            if "customer" in where:
                assert where["customer"] == "ACC-FAKE", (tid, target, where["customer"])
            for f in ("product", "category", "priority"):
                if f in where and target != f:
                    assert where[f] == "v1", (tid, target, f, where[f])
        steps = {s["key"]: s for s in out["steps"]}
        assert list(steps) == KEYS
        # decisions carry their own truth; risks are never scored on one ticket
        assert steps["category"]["truth"] == t["category"] and steps["resolution"]["truth"] == t["resolution"]
        assert steps["priority"]["truth"] == t["priority"] and steps["product"]["truth"] == t["product"]
        for k in ("risk", "upsell"):
            assert steps[k]["correct"] is None and steps[k]["truth"] is None and "happened" in steps[k]
        assert steps["risk"]["happened"] == t["nps_after"]
        assert out["gate"] == "auto"  # the fake is 0.9 sure; AUTO is 0.85


def test_a_known_contact_is_looked_up_and_a_new_address_is_inferred_from_its_domain():
    q = env.load_incoming()
    t = q["tickets"][q["order"][0]]
    fake = _Fake(known=True)
    out = env.envelope(fake, t, q["steps"].get(t["ticket_id"], []))
    assert out["steps"][0]["op"] == "_query support_contacts" and out["steps"][0]["value"] == "ACC-FAKE"
    assert not any(target == "customer" for _, _, _, target in fake.calls)
    fake = _Fake(known=False)
    out = env.envelope(fake, t, q["steps"].get(t["ticket_id"], []))
    who = [(w, target) for kind, _, w, target in fake.calls if target == "customer"]
    assert who == [({"sender_domain": t["sender_domain"]}, "customer")]
    assert out["steps"][0]["value"] == "v1"


def test_the_product_is_a_shortlist():
    q = env.load_incoming()
    t = q["tickets"][q["order"][0]]
    out = env.envelope(_Fake(), t, q["steps"].get(t["ticket_id"], []))
    prod = out["steps"][1]
    assert prod["key"] == "product" and prod["shortlist"]
    assert prod["correct"] == (t["product"] in ["v1", "v2"])


def test_the_first_step_is_scored_on_the_first_real_action_not_a_detour():
    q = env.load_incoming()
    tid = next(i for i in q["order"] if q["steps"].get(i) and q["steps"][i][0]["action"] in env.DETOURS)
    out = env.envelope(_Fake(), q["tickets"][tid], q["steps"][tid])
    truth = next(s for s in out["steps"] if s["key"] == "first_step")["truth"]
    assert truth not in env.DETOURS and truth == next(s["action"] for s in q["steps"][tid] if s["action"] not in env.DETOURS)


def test_a_risk_reads_as_a_multiple_of_the_usual_rate():
    r = env.risk_of("detractor", 0.48, 0.24)
    assert r["risk"]["times"] == 2.0 and r["correct"] is None
    assert env.risk_of("detractor", None, 0.24)["risk"]["times"] is None


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
    assert r.status_code == 200 and r.json()["aito_calls"] == len(KEYS)
    assert c.get("/api/support/status").json()["loaded"] is True

    class _Down(_Fake):
        def predict(self, *a, **k):
            raise app_module.AitoError("503 overloaded")
    monkeypatch.setattr(app_module, "_support_aito", _Down())
    assert c.get("/api/support/envelope", params={"ticket_id": tid}).status_code == 502


def test_parallel_and_sequential_runs_give_the_same_steps():
    q = env.load_incoming()
    for tid in q["order"][:10]:
        t = q["tickets"][tid]
        a = env.envelope(_Fake(), t, q["steps"].get(tid, []), parallel=True)
        b = env.envelope(_Fake(), t, q["steps"].get(tid, []), parallel=False)
        strip = lambda s: {k: v for k, v in s.items() if k != "ms"}  # noqa: E731
        assert [strip(s) for s in a["steps"]] == [strip(s) for s in b["steps"]]
        assert [s["key"] for s in a["steps"]] == KEYS


def test_the_first_step_reads_the_ticket_text_through_the_link():
    q = env.load_incoming()
    t = q["tickets"][q["order"][0]]
    fake = _Fake()
    env.envelope(fake, t, q["steps"].get(t["ticket_id"], []))
    (where,) = [w for kind, table, w, target in fake.calls if table == "support_steps"]
    assert where["ticket.text"] == t["text"] and where["previous_action"] == "start"


class _Tagged(_Fake):
    """Answers each target with its own value ("category" -> "cat-v"), so a step
    fed the wrong upstream value, or none, shows in its inputs."""

    def __init__(self, fail_on=None, **kw):
        super().__init__(**kw)
        self.fail_on = fail_on

    def predict(self, table, where, target, limit=5, select=None):
        self.calls.append(("predict", table, dict(where), target))
        if target == self.fail_on:
            raise app_module.AitoError(f"503 on {target}")
        return {"hits": [{"feature": f"{target[:3]}-v", "$p": 0.9}, {"feature": "other", "$p": 0.05}]}


@pytest.mark.parametrize("parallel", [True, False])
def test_each_step_gets_exactly_its_upstream_inputs(parallel):
    q = env.load_incoming()
    t = q["tickets"][q["order"][0]]
    fake = _Tagged()
    env.envelope(fake, t, q["steps"].get(t["ticket_id"], []), parallel=parallel)
    by_target = {target: w for kind, table, w, target in fake.calls if kind == "predict" and w}
    triage = {"text", "sender", "sender_domain", "channel", "month", "adoption_band", "repeat_30d",
              "customer", "contact", "product", "category"} - {"sender"}
    for target in ("priority", "resolution", "kb_article"):
        assert set(by_target[target]) == triage, target
        assert by_target[target]["category"] == "cat-v" and by_target[target]["product"] == "pro-v", target
    assert by_target["nps_after"]["priority"] == "pri-v" and by_target["nps_after"]["category"] == "cat-v"
    assert set(by_target["action"]) == {"previous_action", "ticket.text", "category"}
    assert by_target["action"]["category"] == "cat-v"


def test_an_error_in_a_parallel_call_surfaces():
    q = env.load_incoming()
    t = q["tickets"][q["order"][0]]
    with pytest.raises(app_module.AitoError, match="503 on resolution"):
        env.envelope(_Tagged(fail_on="resolution"), t, q["steps"].get(t["ticket_id"], []), parallel=True)


def test_your_own_words_carry_no_truth(monkeypatch):
    """Edited text keeps the sender but not what happened to the real ticket."""
    c = TestClient(app_module.app)
    monkeypatch.setitem(app_module._support_state, "checked", 1e18)
    monkeypatch.setitem(app_module._support_state, "loaded", True)
    monkeypatch.setattr(app_module, "_support_aito", _Fake())
    tid = env.load_incoming()["order"][0]
    r = c.get("/api/support/envelope", params={"ticket_id": tid, "text": "What's the weather in Oulu tomorrow?"}).json()
    assert r["edited"] is True and r["ticket"]["text"].startswith("What's the weather")
    assert all(s["truth"] is None and s["correct"] is None and s.get("happened") is None for s in r["steps"])
    same = c.get("/api/support/envelope", params={"ticket_id": tid, "text": env.load_incoming()["tickets"][tid]["text"]})
    assert same.json()["edited"] is False
    assert c.get("/api/support/envelope", params={"ticket_id": tid, "text": "x" * 601}).status_code == 422
