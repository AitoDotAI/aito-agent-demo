"""The Decisions API arm of the benchmark, offline: the request it sends, how it reads an answer,
retries, and that it never makes a call without a key from the environment."""

import json
import sys
from pathlib import Path

import httpx
import pytest

B = Path(__file__).resolve().parents[1] / "scripts" / "bench_banking77"
sys.path.insert(0, str(B))
import decisions  # noqa: E402

LABELS = ["card_arrival", "lost_or_stolen_card", "refund_not_showing_up"]
ANSWER = {"answers": [{"type": "choice", "name": "intent", "choice": "lost_or_stolen_card", "confidence": 0.81,
                       "probabilities": [{"value": "card_arrival", "probability": 0.05},
                                         {"value": "lost_or_stolen_card", "probability": 0.81},
                                         {"value": "refund_not_showing_up", "probability": 0.14}]}]}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_one_choice_question_over_the_labels_with_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json=ANSWER)

    r = decisions.decide("gpt-6-luna", "Which intent?", "Message: i lost my card", LABELS, _client(handler))
    assert seen["url"] == "https://api.openai.com/v1/decisions" and seen["auth"] == "Bearer sk-test"
    q = seen["body"]["questions"]
    assert seen["body"]["model"] == "gpt-6-luna" and seen["body"]["input"] == "Message: i lost my card"
    assert len(q) == 1 and q[0]["type"] == "choice" and [c["value"] for c in q[0]["choices"]] == LABELS
    assert (r["pred"], r["p"]) == ("lost_or_stolen_card", 0.81) and r["top"][0]["intent"] == "lost_or_stolen_card"
    assert r["tokens_estimated"] is True and r["in"] > 0 and r["out"] == 0
    assert "sk-test" not in json.dumps(r)


def test_a_usage_field_is_used_when_the_response_has_one(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    r = decisions.decide("gpt-6-luna", "?", "m", LABELS, _client(lambda req: httpx.Response(200, json={**ANSWER, "usage": {"input_tokens": 321}})))
    assert r["in"] == 321 and r["tokens_estimated"] is False


def test_a_refusal_or_an_unknown_label_is_no_prediction():
    assert decisions.parse({"type": "refusal", "name": "intent"}, LABELS)["pred"] is None
    out = decisions.parse({"type": "choice", "choice": "made_up", "confidence": 0.9}, LABELS)
    assert out["pred"] is None and out["raw"] == "made_up"


def test_rate_limits_are_retried_and_the_backoff_is_reported_apart(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(decisions.time, "sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429 if len(calls) < 3 else 200, json=ANSWER)

    r = decisions.decide("gpt-6-luna", "?", "m", LABELS, _client(handler))
    assert len(calls) == 3 and r["backoff_ms"] == 6000 and r["pred"] == "lost_or_stolen_card"


def test_a_client_error_fails_the_call_and_does_not_retry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad question"}})

    with pytest.raises(RuntimeError, match="HTTP 400"):
        decisions.decide("gpt-6-luna", "?", "m", LABELS, _client(handler))
    assert len(calls) == 1


def test_without_an_openai_key_it_uses_the_azure_resource(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_MODEL_URL", "https://example.cognitive.microsoft.com/")
    monkeypatch.setenv("OPENAI_MODEL_API_KEY", "az-test")
    seen = {}

    def handler(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("api-key")
        return httpx.Response(200, json=ANSWER)

    decisions.decide("gpt-6-luna", "?", "m", LABELS, _client(handler))
    assert seen == {"url": "https://example.cognitive.microsoft.com/openai/v1/decisions", "key": "az-test"}


def test_no_key_means_no_call(monkeypatch):
    for v in ("OPENAI_API_KEY", "OPENAI_MODEL_URL", "OPENAI_MODEL_API_KEY"):
        monkeypatch.delenv(v, raising=False)

    def handler(req):
        raise AssertionError("a request was sent without a key")

    with pytest.raises(SystemExit):
        decisions.decide("gpt-6-luna", "?", "m", LABELS, _client(handler))


def test_input_tokens_are_priced_and_output_is_free():
    assert decisions.usd("gpt-6-luna", 1_000_000, 5_000) == pytest.approx(0.10)
    assert decisions.usd("some-other-model", 1000) is None


def test_summary_scores_a_stated_probability_and_prices_per_million_decisions():
    import summarize
    rows = {f"q{i}": {"qid": f"q{i}", "gold": "a", "pred": "a" if i < 8 else "b", "p": 0.9, "ms": 100.0 + i,
                      "in": 600, "out": 0, "usd": decisions.usd("gpt-6-luna", 600)} for i in range(10)}
    s = summarize.arm_stats(rows, list(rows))
    assert s["calibration_on_sample"]["ece"] == pytest.approx(0.1)        # says 90%, right 80%
    assert s["llm"]["usd_per_1m_decisions"] == pytest.approx(60.0)        # 600 tokens at $0.10 per 1M, a million times
    assert s["llm"]["tokens_estimated_for"] == 0
