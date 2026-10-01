"""The 360 Dashboard and the Company agent's optimize_kpi measure a segment AS the
population (2026-09-30 sanity check): a segment in `where` is evidence, so the
prior, the lever ranking and the projection would still come from every customer.
The current rate is the counted share within the segment; _recommend and the
projection run on a nested `from` scoped to it."""

from src import app as A


class _Recording:
    _ver = "v2"

    def __init__(self):
        self.calls = []

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        self.calls.append(("query", table, dict(where or {})))
        where = where or {}
        # 200 in the segment, 50 of them churned; 1,000 overall
        if "size" in where:
            total = 50 if where.get("churned") == "yes" else (150 if where.get("churned") == "no" else 200)
        else:
            total = 1000
        return {"hits": [], "total": total}

    def predict(self, table, where, target, limit=5, select=None):
        self.calls.append(("predict", table, dict(where)))
        return {"hits": [{"feature": "no", "$p": 0.7}, {"feature": "yes", "$p": 0.3}]}

    def recommend(self, table, where, field, goal, limit=5):
        self.calls.append(("recommend", table, dict(where)))
        return {"hits": [{"feature": "Dedicated", "$p": 0.8}]}

    def relate(self, *a, **k):
        return {"hits": []}

    relate_on = relate


def test_a_segment_is_the_population_not_evidence(monkeypatch):
    fake = _Recording()
    monkeypatch.setattr(A, "aito", fake)
    r = A._tool_optimize_kpi({"kpi": "churn", "size": "SMB", "plan": "Free"})
    seg = {"from": "customers", "where": {"size": "SMB", "plan": "Free"}}
    rec = [c for c in fake.calls if c[0] == "recommend"]
    assert rec and rec[0][1] == seg and rec[0][2] == {}            # the lever ranked within the segment
    proj = [c for c in fake.calls if c[0] == "predict" and c[2] == {"csm_motion": "Dedicated"}]
    assert proj and proj[0][1] == seg                               # the projection, too
    assert r["headline"]["now"] == 0.25                             # 50 of 200 counted, not a model's 0.3
    assert r["current_basis"] == "counted: 150 of 200 retained customers in the segment"


def test_no_segment_means_the_whole_table(monkeypatch):
    fake = _Recording()
    monkeypatch.setattr(A, "aito", fake)
    A._tool_optimize_kpi({"kpi": "churn"})
    assert all(c[1] == "customers" for c in fake.calls if c[0] in ("recommend", "predict"))
