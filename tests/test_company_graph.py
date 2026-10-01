"""The /company spotlight's `$refs` neighbourhood (docs/verification/company-graph.md).

Runs on a fabricated v2 `_query` hit in the live shape (ACC-106944, 2026-09-27), so it
needs no Aito. Every count in the fixture differs from its complement (bad vs good,
active vs inactive, overdue vs paid, detractor vs promoter), so a miscount shows.
"""

from src import app as app_module
from src.aito_client import AitoError

HIT = {"tickets": ["good", "bad", "good", "bad", "good", "good"], "ticket_channels": 4,
       "usage_active": ["no", "yes", "no"], "distinct_products": 3, "deals": ["yes", "no", "no"],
       "invoices": ["overdue", "paid", "paid", "expansion"],
       "feedback": ["detractor", "promoter", "passive"], "feedback_channels": 2}


class _FakeAito:
    def __init__(self, hits=None, fail=False, ver="v2"):
        self.hits, self.fail, self._ver, self.calls = hits, fail, ver, []

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        self.calls.append((table, where, select))
        if table == "customers" and select == app_module._NEIGHBOURHOOD_SELECT:
            if self.fail:
                raise AitoError("400 unknown operator")
            return {"hits": self.hits}
        if table == "customers" and (where or {}).get("customer_id"):
            return {"hits": [{"customer_id": where["customer_id"], "name": "Acme"}]}
        if limit == 0:  # a count (the 360's counted rates)
            return {"hits": [], "total": 10}
        return {"hits": [], "total": 0}


def test_neighbourhood_is_one_query_and_summarises_the_links(monkeypatch):
    fake = _FakeAito([HIT])
    monkeypatch.setattr(app_module, "aito", fake)
    g = app_module._customer_neighbourhood("ACC-106944")
    assert len(fake.calls) == 1
    assert g["tickets"] == {"count": 6, "bad_csat": 2, "channels": 4}
    assert g["usage"] == {"products": 3, "active": 1}
    assert g["deals"] == {"count": 3, "won": 1}
    assert g["invoices"] == {"count": 4, "overdue": 1}
    assert g["feedback"] == {"count": 3, "detractor": 1, "channels": 2}
    assert "not predictions" in g["note"]


def test_every_projection_walks_a_real_link_back_to_the_customer():
    # the $refs paths must name a table that links to customers, and one of its fields
    schema = {"tickets": {"csat_band", "channel"}, "usage": {"active", "product"},
              "deals": {"converted"}, "invoices": {"status"}, "feedback": {"score_band", "channel"}}
    for item in app_module._NEIGHBOURHOOD_SELECT:
        (expr,) = item.values()
        path = expr if isinstance(expr, str) else expr["$distinctLength"]
        _, table, link, field = path.split(".")
        assert link == "customer" and field in schema[table], path


def test_missing_or_null_counts_are_zero(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _FakeAito([{"ticket_channels": None}]))
    g = app_module._customer_neighbourhood("ACC-1")
    assert g["tickets"] == {"count": 0, "bad_csat": 0, "channels": 0}
    assert g["feedback"]["channels"] == 0


def test_unknown_customer_has_no_neighbourhood(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _FakeAito([]))
    assert app_module._customer_neighbourhood("ACC-0") is None


def test_customer_360_adds_the_graph_on_v2_only_and_survives_its_failure(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _FakeAito([HIT], ver="v1"))
    assert "graph" not in app_module._tool_customer_360({"customer_id": "ACC-1"})
    monkeypatch.setattr(app_module, "aito", _FakeAito([HIT]))
    assert app_module._tool_customer_360({"customer_id": "ACC-1"})["graph"]["tickets"]["count"] == 6
    # a failing $refs query drops only the graph, not the profile and domains
    monkeypatch.setattr(app_module, "aito", _FakeAito(fail=True))
    r = app_module._tool_customer_360({"customer_id": "ACC-1"})
    assert r["graph"] is None and r["profile"]["name"] == "Acme" and "tickets" in r["domains"]


def test_a_failed_graph_is_reported_not_just_empty(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _FakeAito(fail=True))
    assert app_module._tool_customer_360({"customer_id": "ACC-1"})["graph_unavailable"] is True
    monkeypatch.setattr(app_module, "aito", _FakeAito([]))  # no neighbourhood is not a failure
    assert "graph_unavailable" not in app_module._tool_customer_360({"customer_id": "ACC-1"})


def test_company_360_names_what_fell_back_to_empty(monkeypatch):
    """A failing _relate reads as "no driver"; `degraded` tells the two apart (the live
    smoke asserts it is empty)."""
    from fastapi.testclient import TestClient

    class _Relating(_FakeAito):
        def __init__(self, relate_fails):
            super().__init__([HIT])
            self.relate_fails = relate_fails

        def predict(self, table, where, target, limit=5, select=None):
            return {"hits": [{"feature": "yes", "$p": 0.6}, {"feature": "no", "$p": 0.4}]}

        def relate(self, *a, **k):
            if self.relate_fails:
                raise AitoError("500 relate")
            return {"hits": []}

        relate_on = relate

        def recommend(self, *a, **k):
            return {"hits": []}

    monkeypatch.setattr(app_module, "_tool_find_examples", lambda args: {"rows": [{"customer_id": "ACC-1"}]})
    c = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "aito", _Relating(relate_fails=False))
    ok = c.get("/api/company-360").json()
    assert ok["degraded"] == [] and all(not k["causes"] for k in ok["kpis"])  # no driver, and that's real
    monkeypatch.setattr(app_module, "aito", _Relating(relate_fails=True))
    bad = c.get("/api/company-360").json()
    assert bad["degraded"] == [f"causes:{k['key']}" for k in bad["kpis"]] and len(bad["degraded"]) == 6
    assert all(k["causes_unavailable"] for k in bad["kpis"])


def test_the_at_risk_spotlight_is_a_current_customer_not_a_churned_one(monkeypatch):
    """The spotlight is labelled "at risk": it must be someone who has not churned yet,
    picked for an observable risk (health Red first), and say why."""
    from fastapi.testclient import TestClient
    people = [
        {"customer_id": "ACC-1", "name": "Gone Oy", "health": "Red", "churned": "yes", "size": "SMB", "plan": "Free"},
        {"customer_id": "ACC-2", "name": "Wobbly Oy", "health": "Red", "churned": "no", "size": "SMB", "plan": "Free"},
        {"customer_id": "ACC-3", "name": "Fine Oy", "health": "Green", "churned": "no", "size": "SMB", "plan": "Free"},
    ]

    class _People(_FakeAito):
        def query(self, table, where=None, select=None, order_by=None, limit=5):
            if table == "customers" and select != app_module._NEIGHBOURHOOD_SELECT:
                rows = [p for p in people if all(p.get(k) == v for k, v in (where or {}).items())]
                return {"hits": rows[:limit], "total": len(rows)}
            return super().query(table, where, select, order_by, limit)

        def predict(self, *a, **k):
            return {"hits": [{"feature": "no", "$p": 0.7}, {"feature": "yes", "$p": 0.3}]}

        def relate(self, *a, **k):
            return {"hits": []}

        relate_on = relate

        def recommend(self, *a, **k):
            return {"hits": []}

    monkeypatch.setattr(app_module, "aito", _People([HIT]))
    c = TestClient(app_module.app).get("/api/company-360").json()["customer"]
    assert c["profile"]["customer_id"] == "ACC-2" and c["profile"]["churned"] == "no"
    assert "health Red" in c["why_spotlight"]
    # no current Red customer: the next observable risk, Yellow, not a churned Red one
    people[1]["churned"] = "yes"
    people.append({"customer_id": "ACC-4", "name": "Meh Oy", "health": "Yellow", "churned": "no", "size": "SMB", "plan": "Free"})
    c = TestClient(app_module.app).get("/api/company-360").json()["customer"]
    assert c["profile"]["customer_id"] == "ACC-4" and "health Yellow" in c["why_spotlight"]
