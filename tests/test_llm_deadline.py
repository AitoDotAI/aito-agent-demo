"""An LLM call with a deadline gives up on time, retries and backoff included."""

import time
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from src import llm_agent


class _SlowClient:
    def __init__(self):
        self.options = []

    def with_options(self, **kw):
        self.options.append(kw)
        return self

    @property
    def chat(self):
        def create(**_):
            time.sleep(0.3)
            raise APITimeoutError(request=httpx.Request("POST", "http://x"))
        return SimpleNamespace(completions=SimpleNamespace(create=create))


def test_deadline_stops_retries(monkeypatch):
    agent = llm_agent.LLMAgent.__new__(llm_agent.LLMAgent)
    agent._client, agent._deployment = _SlowClient(), "slow"
    t0 = time.monotonic()
    with pytest.raises(TimeoutError, match="slow did not answer within 2 s"):
        agent._create({}, {}, deadline_s=2)
    assert time.monotonic() - t0 < 2.5
    assert all(o["max_retries"] == 0 and o["timeout"] <= 2 for o in agent._client.options)


def test_the_support_reply_route_is_rate_limited(monkeypatch):
    from fastapi.testclient import TestClient
    from src import app as A
    monkeypatch.setattr(A, "_rl_hits", {})
    c = TestClient(A.app)
    codes = [c.post("/api/support/reply", json={"ticket_id": "SUP-nope"}, headers={"x-forwarded-for": "9.9.9.9"}).status_code
             for _ in range(8)]
    assert codes[:6] == [404] * 6 and codes[6:] == [429, 429]
    # another visitor is unaffected
    assert c.post("/api/support/reply", json={"ticket_id": "SUP-nope"}, headers={"x-forwarded-for": "8.8.8.8"}).status_code == 404
