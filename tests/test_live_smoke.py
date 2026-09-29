"""The live smoke's content checks (scripts/live_smoke.py), offline."""
import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "live_smoke", Path(__file__).resolve().parents[1] / "scripts" / "live_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["live_smoke"] = smoke          # @dataclass looks its module up here
_spec.loader.exec_module(smoke)


def _kpi(key, causes):
    return {"key": key, "current": 0.5, "causes": [{"f": "x"}] * causes}


def _c360(causes_per_kpi):
    keys = ["conversion", "churn", "nps", "csat", "adoption", "ontime"]
    return {"kpis": [_kpi(k, c) for k, c in zip(keys, causes_per_kpi)],
            "customer": {"profile": {"id": "c1"}}}


def test_company_360_tolerates_a_kpi_without_causes():
    # 29.9: ontime 0 causes (a weak lift is plausible), the others filled
    assert "5 with causes" in smoke.check_company_360(_c360([1, 3, 1, 2, 1, 0]))


def test_company_360_fails_when_relate_is_silently_broken():
    # _relate_drivers returns [] on an AitoError: all-empty is the failure it hides
    with pytest.raises(AssertionError, match="_relate"):
        smoke.check_company_360(_c360([0, 0, 0, 0, 1, 0]))


def test_resolve_needs_a_confident_intent_with_reasons():
    with pytest.raises(AssertionError, match="no \\$why"):
        smoke.check_resolve({"intent": "check_outage", "intent_p": 0.98, "why": []})
    assert "check_outage" in smoke.check_resolve(
        {"intent": "check_outage", "intent_p": 0.98, "why": [{"x": 1}], "param_field": "location", "param": "Helsinki"})


def test_handoff_counts_must_add_up():
    with pytest.raises(AssertionError, match="add up"):
        smoke.check_handoff({"total": 10, "counts": {"auto": 7, "assist": 0, "handoff": 2}})


def test_no_llm_route_is_called():
    paths = {s.path for s in smoke.STEPS}
    assert not paths & {"/api/resolve-llm", "/api/route", "/api/sales-agent/chat", "/api/company-agent/chat"}


def test_every_step_is_a_get(monkeypatch):
    methods = []

    class _Res:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def urlopen(req, timeout):
        methods.append(req.get_method())
        return _Res()
    monkeypatch.setattr(smoke.urllib.request, "urlopen", urlopen)
    for step in smoke.STEPS:
        smoke.fetch("http://x", step, 1)
    assert set(methods) == {"GET"} and len(methods) == len(smoke.STEPS)
