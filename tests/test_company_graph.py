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
        if table == "customers":
            return {"hits": [{"customer_id": where["customer_id"], "name": "Acme"}]}
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
