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


class _Empty(_Recording):
    """A segment with no rows: counts are 0, and (on shared 2.11.2) any nested `from`
    over it answers 400 request.invalid "... matched no rows" instead of an empty result."""

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        self.calls.append(("query", table, dict(where or {})))
        return {"hits": [], "total": 0}

    def _nested(self, table):
        if isinstance(table, dict):
            raise A.AitoError("400", status_code=400,
                              body={"kind": "error", "data": {"code": "request.invalid",
                                                               "message": "the nested from matched no rows"}})

    def predict(self, table, where, target, limit=5, select=None):
        self._nested(table)
        return super().predict(table, where, target, limit, select)

    def recommend(self, table, where, field, goal, limit=5):
        self._nested(table)
        return super().recommend(table, where, field, goal, limit)


def test_an_empty_segment_is_an_empty_state_not_an_error(monkeypatch):
    from fastapi.testclient import TestClient
    fake = _Empty()
    monkeypatch.setattr(A, "aito", fake)
    r = A._tool_optimize_kpi({"kpi": "churn", "size": "SMB", "plan": "Free"})
    assert r["empty"] is True and r["headline"]["now"] is None and r["levers"]["items"] == []
    assert not [c for c in fake.calls if c[0] in ("recommend",) or (c[0] == "predict" and isinstance(c[1], dict))]
    monkeypatch.setattr(A, "_tool_find_examples", lambda args: {"rows": []})
    resp = TestClient(A.app).get("/api/company-360", params={"size": "SMB", "plan": "Free"})
    assert resp.status_code == 200 and all(k["empty"] for k in resp.json()["kpis"])


def test_a_matched_no_rows_400_reads_as_empty(monkeypatch):
    """If the count and the nested from ever disagree, the engine's 400 is still an empty population."""
    class _Disagree(_Empty):
        def query(self, table, where=None, select=None, order_by=None, limit=5):
            return {"hits": [], "total": 5}
    monkeypatch.setattr(A, "aito", _Disagree())
    r = A._tool_optimize_kpi({"kpi": "churn", "size": "SMB", "plan": "Free"})
    assert r["levers"]["items"] == [] and r["recommended_play"]["change_to"] is None


def test_the_kpis_run_concurrently_and_keep_their_order(monkeypatch):
    """Each KPI makes about seven Aito calls; run one after another the 360 took 12-21 s on prod."""
    import threading
    import time
    from fastapi.testclient import TestClient
    seen = set()

    class _Slow(_Recording):
        def query(self, table, where=None, select=None, order_by=None, limit=5):
            seen.add(threading.get_ident())
            time.sleep(0.05)
            return super().query(table, where, select, order_by, limit)

    monkeypatch.setattr(A, "aito", _Slow())
    monkeypatch.setattr(A, "_tool_find_examples", lambda args: {"rows": []})
    out = TestClient(A.app).get("/api/company-360", params={"size": "SMB"}).json()
    assert [k["key"] for k in out["kpis"]] == list(A._KPIS)
    assert len(seen) > 1                                    # more than one thread did the work


def test_a_good_direction_card_shows_one_number_for_the_top_lever(monkeypatch):
    """The lever badge and the sentence under it ("... with X: 53% vs 39%") named the same
    outcome but came from two queries (_recommend and _predict), 1-2 points apart on prod.
    For a KPI whose good outcome is what the card reports, the lever's own p is the number."""
    class _Apart(_Recording):
        def predict(self, table, where, target, limit=5, select=None):
            self.calls.append(("predict", table, dict(where)))
            return {"hits": [{"feature": "yes", "$p": 0.53}, {"feature": "no", "$p": 0.47}]}

        def recommend(self, table, where, field, goal, limit=5):
            self.calls.append(("recommend", table, dict(where)))
            return {"hits": [{"feature": "Self-serve", "$p": 0.55}]}

    monkeypatch.setattr(A, "aito", _Apart())
    r = A._tool_optimize_kpi({"kpi": "conversion", "size": "SMB", "plan": "Free"})
    assert r["levers"]["items"][0]["p"] == 0.55
    assert r["headline"]["then"] == 0.55 and r["projected"] == 0.55


def test_a_lower_is_better_card_shows_the_lever_lift_on_the_outcome_it_reports(monkeypatch):
    """Churn, NPS and on-time report the BAD outcome in the headline. The lever badge used to
    be the good outcome's lift (retention x1.07) next to a falling churn rate (32% -> 27%);
    it now reads on the same outcome as the headline: P(churned | lever) / the segment's rate."""
    class _Churn(_Recording):
        def predict(self, table, where, target, limit=5, select=None):
            self.calls.append(("predict", table, dict(where)))
            p = 0.2 if where.get("csm_motion") == "Dedicated" else 0.3
            return {"hits": [{"feature": "yes", "$p": p}, {"feature": "no", "$p": 1 - p}]}

    monkeypatch.setattr(A, "aito", _Churn())
    r = A._tool_optimize_kpi({"kpi": "churn", "size": "SMB", "plan": "Free"})
    top = r["levers"]["items"][0]
    assert top["value"] == "Dedicated" and top["p"] == 0.2          # P(churned | Dedicated)
    assert top["lift"] == 0.8                                       # 0.2 / the segment's counted 0.25
    assert r["headline"]["then"] == top["p"] and r["headline"]["now"] == 0.25
    assert r["levers"]["outcome"] == "churned customers"
