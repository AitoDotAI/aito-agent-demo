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
    codes = [c.get("/api/route", params={"text": "x"}, headers={"x-forwarded-for": "7.7.7.7"}).status_code
             for _ in range(3)]
    assert codes == [502, 502, 429]
