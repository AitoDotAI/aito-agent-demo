"""Query panes show the query that was sent (2026-09-30 sanity check, item c; the
pattern from aito-erp-demo docs/design/query-panes.md). The client records each
request body at its one send path; routes return them as `_queries`; the page renders
them. Credentials never reach a record, and no page writes query text by hand."""

import json
import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from src import app as A
from src.aito_client import AitoClient
from src.config import Config

SENTINEL = "SENTINEL-KEY-0f3c"
FRONT = Path(__file__).resolve().parents[1] / "frontend" / "components"


def _client(env=None):
    """A real AitoClient whose HTTP goes to a mock that answers every op."""
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        if req.url.path.endswith("_query"):
            return httpx.Response(200, json={"hits": [], "total": 0})
        target = body.get("predict") or body.get("recommend") or "x"
        return httpx.Response(200, json={"hits": [{"$value": f"{target}-v", "$p": 0.9}, {"$value": "other", "$p": 0.1}]})
    c = AitoClient(Config(aito_url="https://example.aito.app/db/demo" + (f"/env/{env}" if env else ""),
                          aito_key=SENTINEL, aito_api_version="v2", aito_env=env))
    c._http = httpx.Client(base_url=c._url, headers=c._headers, transport=httpx.MockTransport(handler))
    return c


def test_handoff_returns_the_bodies_it_sent_and_no_credentials(monkeypatch):
    monkeypatch.setattr(A, "aito", _client())
    r = TestClient(A.app).get("/api/handoff")
    q = r.json()["_queries"]
    assert q and q[0]["op"] == "_predict" and q[0]["path"] == "/api/v2/_predict"
    assert q[0]["body"] == {"from": "resolutions", "where": {"text": A._HANDOFF_QUEUE[0]}, "predict": "intent",
                            "limit": 3, "select": ["$p", "$value"]}
    assert SENTINEL not in r.text and "example.aito.app" not in r.text


def test_the_envelope_records_its_thread_pool_calls_and_keeps_them_on_a_cache_hit(monkeypatch):
    from src import support_envelope as env
    monkeypatch.setitem(A._support_state, "checked", 1e18)
    monkeypatch.setitem(A._support_state, "loaded", True)
    monkeypatch.setattr(A, "_envelopes", {})
    monkeypatch.setattr(A, "_support_aito", _client("support"))
    tid = env.load_incoming()["order"][0]
    c = TestClient(A.app)
    first = c.get("/api/support/envelope", params={"ticket_id": tid}).json()["_queries"]
    targets = {q["body"].get("predict") or q["body"].get("recommend") for q in first}
    assert {"priority", "resolution", "kb_article", "action", "nps_after", "recovery"} <= targets   # pool threads too
    assert all(q["env"] == "support" for q in first)
    again = c.get("/api/support/envelope", params={"ticket_id": tid}).json()["_queries"]
    assert again == first                                                                            # cached with the value


def test_no_panel_writes_query_text_by_hand():
    src = (FRONT / "AppShell.tsx").read_text()
    panes = re.findall(r'code: "((?:[^"\\]|\\.)*)"', src)
    hand_written = [p for p in panes if '\\"from\\"' in p or re.search(r"POST /api/v\d/_", p)]
    assert not hand_written, hand_written
    assert "&quot;from&quot;" not in src, "a hand-written JSX query pane"
