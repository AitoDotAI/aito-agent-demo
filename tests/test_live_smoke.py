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


def test_degraded_names_the_failure():
    body = {**_c360([1, 3, 1, 2, 1, 0]), "degraded": ["causes:ontime"]}
    with pytest.raises(AssertionError, match="causes:ontime"):
        smoke.check_company_360(body)
    assert "nothing degraded" in smoke.check_company_360({**_c360([1, 0, 0, 0, 0, 0]), "degraded": []})
    with pytest.raises(AssertionError, match="backstop"):
        smoke.check_company_360({**_c360([0, 0, 0, 0, 0, 0]), "degraded": []})


def test_require_degraded_fails_a_build_without_the_field(monkeypatch):
    monkeypatch.setattr(smoke, "REQUIRE_DEGRADED", True)
    with pytest.raises(AssertionError, match="require-degraded"):
        smoke.check_company_360(_c360([1, 3, 1, 2, 1, 0]))


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
    # the app's own list of billable LLM routes, so a new one is covered automatically;
    # /api/route also calls the LLM and is being added to _LLM_PATHS separately
    # read from the source: importing src.app needs Aito credentials
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" / "app.py").read_text())
    llm_paths = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                     if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "_LLM_PATHS" for t in n.targets))
    assert "/api/resolve-llm" in llm_paths      # guards against reading the wrong assignment
    assert "/api/route" in llm_paths            # #23: the route that calls the LLM is listed too
    forbidden = set(llm_paths)
    assert not {s.path for s in smoke.STEPS} & forbidden


def test_a_dropped_connection_is_a_recorded_failure_not_a_crash(monkeypatch, capsys):
    import http.client

    def urlopen(req, timeout):
        raise http.client.RemoteDisconnected("Remote end closed connection without response")
    monkeypatch.setattr(smoke.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(smoke.sys, "argv", ["live_smoke.py", "--base", "http://x"])
    assert smoke.main() == 1
    out = capsys.readouterr().out
    assert f"{len(smoke.STEPS)} of {len(smoke.STEPS)} views FAILED" in out


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
