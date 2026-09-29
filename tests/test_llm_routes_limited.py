"""Every route that reaches the LLM is rate-limited: the list is checked against the
routes' own code, so a new LLM route can't be added without its limit."""

import inspect

from fastapi.routing import APIRoute

from src import app as A

#: what calling the LLM looks like in a route's body
_MARKERS = ("get_agent", "run_turn", "draft_reply")


def _calls_llm(route: APIRoute) -> bool:
    return any(m in inspect.getsource(route.endpoint) for m in _MARKERS)


def test_every_llm_route_is_rate_limited():
    llm = {r.path for r in A.app.routes if isinstance(r, APIRoute) and _calls_llm(r)}
    assert llm, "the markers found no LLM route at all: they are stale"
    assert llm <= A._LLM_PATHS, f"LLM routes without a rate limit: {sorted(llm - A._LLM_PATHS)}"


def test_route_is_limited(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(A, "_rl_hits", {})
    monkeypatch.setattr(A, "_RL_MAX", 2)
    monkeypatch.setattr(A.aito, "predict", lambda *a, **k: (_ for _ in ()).throw(A.AitoError("down")))
    c = TestClient(A.app)
    codes = [c.post("/api/route", json={"text": "x"}, headers={"x-forwarded-for": "7.7.7.7"}).status_code
             for _ in range(3)]
    assert codes == [502, 502, 429]


def test_llm_routes_are_post_only():
    """A GET that spends LLM tokens is one link preview or crawler away from spending them."""
    from fastapi.testclient import TestClient
    c = TestClient(A.app)
    for path in ("/api/route", "/api/resolve-llm"):
        assert c.get(path, params={"text": "hi"}).status_code in (404, 405), path  # 404: the static mount


def test_long_text_and_a_spent_budget_stop_before_any_llm_call(monkeypatch):
    from fastapi.testclient import TestClient
    from src import llm_agent

    def no_llm(*a, **k):
        raise AssertionError("the LLM must not be called")
    monkeypatch.setattr(llm_agent, "get_agent", no_llm)
    monkeypatch.setattr(A, "_rl_hits", {})
    c = TestClient(A.app)
    for path in ("/api/route", "/api/resolve-llm"):
        assert c.post(path, json={"text": "x" * (A._LLM_TEXT_MAX + 1)}).status_code == 422
    monkeypatch.setattr(llm_agent, "_spent", {"day": None, "tokens": 0})
    monkeypatch.setattr(llm_agent, "DAILY_TOKENS", 0)
    for path in ("/api/route", "/api/resolve-llm"):
        r = c.post(path, json={"text": "my internet is down"})
        assert r.status_code == 429 and "paused for today" in r.json()["detail"], path


def test_calls_are_counted_against_the_budget(monkeypatch):
    from src import llm_agent
    monkeypatch.setattr(llm_agent, "_spent", {"day": None, "tokens": 0})
    monkeypatch.setattr(llm_agent, "DAILY_TOKENS", 1000)
    llm_agent.spend(600)
    assert llm_agent.budget_left() == 400
    llm_agent.spend(500)
    assert llm_agent.budget_left() == -100
