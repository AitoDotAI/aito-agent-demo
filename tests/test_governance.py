"""Governance rule mining (use case #15): the rule arithmetic, the candidate and
strong cut-offs, and the API shapes that mirror aito-accounting-demo ADR 0025.
Runs on fabricated _relate hits in the live v2 shape, so it needs no Aito."""

from fastapi.testclient import TestClient

from src import app as app_module
from src import governance as gov


def _hit(related, match, total, of_target):
    return {"related": related, "lift": 5.0,
            "fs": {"fOnCondition": float(match), "f": float(total), "fCondition": float(of_target), "n": 4000.0}}


def test_a_rule_reads_precision_and_coverage_the_right_way_round():
    # live: text has "refund" fires on 532 tickets, all refunds, of 667 refunds
    r = gov.rule_from_hit(_hit({"text": {"$has": "refund"}}, 532, 532, 667), "intent", "refund")
    assert r["rule"] == {"conditions": [{"field": "text", "op": "has", "value": "refund"}],
                         "target": {"field": "intent", "value": "refund"}}
    assert r["support"] == {"match": 532, "total": 532}
    assert (r["precision"], r["coverage"], r["strength"]) == (1.0, 0.798, "strong")
    # fires on 40, right on 30, of 300 decisions of that value
    r = gov.rule_from_hit(_hit({"customer": "acme"}, 30, 40, 300), "intent", "refund")
    assert r["rule"]["conditions"] == [{"field": "customer", "op": "is", "value": "acme"}]
    assert (r["precision"], r["coverage"], r["strength"]) == (0.75, 0.1, "candidate")


def test_strong_needs_both_precision_and_enough_decisions():
    few = gov.rule_from_hit(_hit({"text": {"$has": "bill"}}, 11, 11, 25), "tool", "check_invoice")
    assert few["precision"] == 1.0 and few["strength"] == "candidate"  # 11 < STRONG_MATCH


class _FakeAito:
    def __init__(self):
        self.relate_calls = []

    def query(self, table, where=None, select=None, order_by=None, limit=5):
        return {"hits": [{"intent": "refund"}] * 3 + [{"intent": "find_shop"}] * 2 + [{}]}

    def relate(self, table, where, fields, limit=None):
        self.relate_calls.append(where)
        if where == {"intent": "refund"}:
            return {"hits": [_hit({"text": {"$has": "for"}}, 256, 256, 667),        # precise, narrow
                             _hit({"text": {"$has": "refund"}}, 532, 532, 667),     # precise, broad
                             _hit({"text": {"$has": "my"}}, 600, 1641, 667)]}       # a common word
        return {"hits": [_hit({"text": {"$has": "shop"}}, 264, 264, 667)]}


def test_mining_keeps_precise_rules_and_ranks_by_precision_times_coverage():
    fake = _FakeAito()
    out = gov.mine_rules(fake, "resolutions")
    assert fake.relate_calls == [{"intent": "find_shop"}, {"intent": "refund"}]  # one per value, None skipped
    assert out["decisions"] == 6 and out["decision_values"] == 2
    values = [r["rule"]["conditions"][0]["value"] for r in out["rules"]]
    assert values == ["refund", "shop", "for"]  # "my" (37% right) is not a candidate
    assert out["strong"] == 3


def test_routes_validate_the_log_and_say_nothing_is_in_force(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _FakeAito())
    app_module._GOV_CACHE.clear()
    c = TestClient(app_module.app)
    assert c.get("/api/governance/rules", params={"log": "users"}).status_code == 400
    body = c.get("/api/governance/rules").json()
    assert body["log"] == "resolutions" and body["logs"]["tool_calls"] == "tool routing"
    active = c.get("/api/rules/active").json()
    assert active["rules"] == [] and active["writable"] is False
    app_module._GOV_CACHE.clear()
