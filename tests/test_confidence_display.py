"""Confidence on screen is the real $p, and one gate decides "sure" everywhere
(2026-09-30 sanity check, item e: ConfidenceBar capped every $p at 0.99, and the
Tool routing view used a 0.9 gate while the rest of the app uses 0.85)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"


def test_one_gate_in_python_and_typescript():
    from src import gates
    from src import app as A
    from src import support_envelope as env
    assert (A._AUTO_GATE, A._ASSIST_GATE) == (env.AUTO, env.ASSIST) == (gates.AUTO_GATE, gates.ASSIST_GATE)
    ts = (FRONT / "lib" / "gates.ts").read_text()
    assert float(re.search(r"AUTO_GATE = ([0-9.]+)", ts).group(1)) == gates.AUTO_GATE
    assert float(re.search(r"ASSIST_GATE = ([0-9.]+)", ts).group(1)) == gates.ASSIST_GATE


def test_no_component_caps_or_hardcodes_a_confidence():
    for f in (FRONT / "components").rglob("*.tsx"):
        src = f.read_text()
        assert not re.search(r"Math\.min\(\s*\w+\s*,\s*0\.99\s*\)", src), f"{f.name}: caps $p at 0.99"
        assert not re.search(r"(?:top|p|value|conf)\s*>=\s*0\.\d+", src), f"{f.name}: a literal confidence gate"


def test_the_band_is_decided_in_one_place():
    """td-20260919195009050217: /api/handoff and scripts/live_smoke.py have to agree
    on which band a $p is in, or the gate asserts a band the demo does not serve."""
    from src import gates
    from src import app as A
    assert all(gates.band_of(p) == b for p, b in
               [(1.0, "auto"), (gates.AUTO_GATE, "auto"), (gates.AUTO_GATE - 1e-9, "assist"),
                (gates.ASSIST_GATE, "assist"), (gates.ASSIST_GATE - 1e-9, "handoff"), (0.0, "handoff")])
    # sensitive is handed off from the assist gate up, and is already a handoff below it
    assert all(gates.band_of(p, True) == "handoff" for p in (1.0, 0.9, gates.ASSIST_GATE, 0.1))
    # the nearest gate, and the signed distance to it
    assert gates.margin_to_gate(gates.AUTO_GATE + 0.0011) == ("auto", pytest.approx(0.0011))
    assert gates.margin_to_gate(gates.ASSIST_GATE - 0.0011) == ("assist", pytest.approx(-0.0011))
    assert gates.margin_to_gate(0.75)[0] == "auto"      # 0.75 is equidistant-ish; ties go to auto
    assert A.band_of is gates.band_of


def test_the_reported_margin_skips_rows_whose_band_their_p_does_not_decide():
    from src import app as A
    rows = [
        {"text": "sure thing", "intent": "repair_help", "p": 0.95, "band": "auto"},
        {"text": "a hair over", "intent": "check_outage", "p": A.AUTO_GATE + 0.0011, "band": "auto"},
        # a refund at exactly the gate: handed off whatever its $p, so a zero distance
        # here would read as "about to flip" when nothing about it can flip
        {"text": "refund me", "intent": "refund", "p": A.AUTO_GATE, "band": "handoff"},
    ]
    m = A._band_margin(rows)
    assert m["text"] == "a hair over" and m["gate"] == "auto"
    assert m["delta"] == pytest.approx(0.0011) and m["band"] == "auto"
    assert A._band_margin([r for r in rows if r["intent"] in A._SENSITIVE]) is None


def test_the_endpoint_serves_the_margin_the_gate_can_require(monkeypatch):
    """The two halves meet: /api/handoff reports `margin`, and the live gate run
    with --require-margin accepts that body instead of tolerating its absence."""
    import importlib.util
    import json
    import sys

    import httpx
    from fastapi.testclient import TestClient

    from src import app as A
    from src.aito_client import AitoClient
    from src.config import Config

    # every ticket predicts `repair_help`, one of them a thousandth over the auto gate
    ps = iter([A.AUTO_GATE + 0.0011] + [0.95] * 20)

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        target = body.get("predict") or "x"
        return httpx.Response(200, json={"hits": [{"$value": "repair_help", "$p": next(ps)},
                                                  {"$value": "refund", "$p": 0.01}]})
    c = AitoClient(Config(aito_url="https://example.aito.app/db/demo", aito_key="SENTINEL",
                          aito_api_version="v2", aito_env=None))
    c._http = httpx.Client(base_url=c._url, headers=c._headers, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(A, "aito", c)

    body = TestClient(A.app).get("/api/handoff").json()
    assert body["margin"]["delta"] == pytest.approx(0.0011)
    assert body["margin"]["gate"] == "auto" and body["margin"]["band"] == "auto"

    spec = importlib.util.spec_from_file_location("live_smoke", ROOT / "scripts" / "live_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    sys.modules["live_smoke"] = smoke
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "REQUIRE_MARGIN", True)
    monkeypatch.setattr(smoke, "EXPECTED_BANDS", body["counts"])
    assert "+0.0011 from the auto gate" in smoke.check_handoff(body)
