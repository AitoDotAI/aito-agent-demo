"""The /company spotlight's `$refs` neighbourhood (docs/verification/company-graph.md).

Runs on a fabricated v2 `_query` hit in the live shape (ACC-106944, 2026-09-27), so it
needs no Aito. Its real CSAT mix is 3 good / 3 bad, which cannot tell "bad" from "good",
so the fixture uses 4 / 2. The live cross-check is that these counts equal the per-domain `_query`
totals for the same customer.
"""

from src import app as app_module

LIVE_HIT = {"tickets": ["good", "bad", "good", "bad", "good", "good"], "ticket_channels": 4,
            "usage_active": ["no", "no"], "distinct_products": 2, "deals": ["yes", "no"],
            "invoices": ["overdue"], "feedback": [], "feedback_channels": 0}


class _FakeAito:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        self.calls.append((table, where, select))
        return {"hits": self.hits}


def test_neighbourhood_is_one_query_and_summarises_the_links(monkeypatch):
    fake = _FakeAito([LIVE_HIT])
    monkeypatch.setattr(app_module, "aito", fake)
    g = app_module._customer_neighbourhood("ACC-106944")
    assert len(fake.calls) == 1 and fake.calls[0][0] == "customers"
    assert g["tickets"] == {"count": 6, "bad_csat": 2, "channels": 4}
    assert g["usage"] == {"products": 2, "active": 0}
    assert g["deals"] == {"count": 2, "won": 1}
    assert g["invoices"] == {"count": 1, "overdue": 1}
    assert g["feedback"] == {"count": 0, "detractor": 0, "channels": 0}
    assert "not predictions" in g["note"]


def test_unknown_customer_has_no_neighbourhood(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _FakeAito([]))
    assert app_module._customer_neighbourhood("ACC-0") is None
