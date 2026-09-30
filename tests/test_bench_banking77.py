"""The banking77 benchmark's statistics and sampling, offline. The data-dependent
tests skip when the dataset hasn't been fetched (scripts/bench_banking77/fetch.py)."""

import json
import sys
from pathlib import Path

import pytest

B = Path(__file__).resolve().parents[1] / "scripts" / "bench_banking77"
sys.path.insert(0, str(B))
import common  # noqa: E402

HAVE_DATA = all((common.DATA / n).exists() for n in common.SHA256)


def test_wilson_matches_known_values():
    assert common.wilson(0, 0) is None
    lo, hi = common.wilson(50, 100)
    assert (lo, hi) == (0.4038, 0.5962)
    lo, hi = common.wilson(100, 100)
    assert hi == 1.0 and 0.96 < lo < 0.97


def test_mcnemar_counts_only_discordant_pairs():
    a = [True] * 50 + [True] * 10 + [False] * 2 + [False] * 38
    b = [True] * 50 + [False] * 10 + [True] * 2 + [False] * 38
    m = common.mcnemar(a, b)
    assert (m["only_first_right"], m["only_second_right"]) == (10, 2)
    assert m["p"] == pytest.approx(0.0386, abs=1e-4)       # exact binomial, n=12, k=2
    assert common.mcnemar(a, a)["p"] == 1.0


def test_ece_is_zero_when_stated_equals_right_and_large_when_not():
    assert common.ece([(0.75, True)] * 3 + [(0.75, False)])["ece"] == 0.0
    assert common.ece([(0.95, False)] * 10)["ece"] == 0.95


def test_jsonl_resumes_with_the_last_line_winning(tmp_path):
    p = tmp_path / "arm.jsonl"
    p.write_text(json.dumps({"qid": "a", "pred": "x"}) + "\n" + json.dumps({"qid": "a", "pred": "y"}) + "\n")
    assert common.jsonl(p) == {"a": {"qid": "a", "pred": "y"}}


@pytest.mark.skipif(not HAVE_DATA, reason="banking77 not fetched")
def test_the_split_and_sample_are_pinned_and_never_leak():
    train, test, dropped = common.split()
    assert (len(train), len(test), dropped) == (10003, 3073, 7)
    seen = {common.norm(r["text"]) for r in train}
    assert not any(common.norm(r["text"]) in seen for r in test)       # no test text is in train
    s = common.sample(test)
    assert len(s) == 616 and len({r["qid"] for r in s}) == 616
    counts = {}
    for r in s:
        counts[r["intent"]] = counts.get(r["intent"], 0) + 1
    assert set(counts.values()) == {common.PER_INTENT} and len(counts) == 77
    assert [r["qid"] for r in common.sample(test)] == [r["qid"] for r in s]   # same seed, same sample


def test_prompts_carry_what_each_arm_is_given():
    import run
    q = {"text": "my card has not arrived", "intent": "card_arrival"}
    allowed = ["card_arrival", "card_delivery_estimate"]
    zero = run.prompt(q, allowed)
    assert "Allowed intents: card_arrival, card_delivery_estimate" in zero and "history" not in zero
    rag = run.prompt(q, allowed, examples=[{"text": "card still not here", "intent": "card_arrival"}])
    assert '- "card still not here" -> card_arrival' in rag
    coop = run.prompt(q, allowed, aito={"top": [{"intent": "card_arrival", "p": 0.81}], "why": '"arriv" (x3.2)'})
    assert "history suggests: card_arrival (0.81)" in coop and "Words behind the first suggestion" in coop


def test_why_words_come_from_the_lift_leaves():
    import run
    # the live shape (banking77 env, 2026-09-30): single words, and $group of words
    why = {"type": "product", "factors": [
        {"type": "baseP", "value": 0.016, "proposition": {"intent": {"$has": "Refund_not_showing_up"}}},
        {"type": "relatedPropositionLift", "proposition": {"text": "showing"}, "value": 3.88},
        {"type": "relatedPropositionLift", "proposition": {"$group": [{"text": "but"}, {"text": "I"}]}, "value": 3.40},
        {"type": "relatedPropositionLift", "proposition": {"text": "refund"}, "value": 32.0},
        {"type": "relatedPropositionLift", "proposition": {"text": "the"}, "value": 0.9}]}
    assert run._words(why) == '"refund" (x32.0), "showing" (x3.9), "but + I" (x3.4)'


def test_gated_threshold_is_fit_and_scored_on_disjoint_halves(monkeypatch, tmp_path):
    import summarize
    qids = [f"q{i}" for i in range(20)]
    aito = {q: {"qid": q, "gold": "a", "pred": "a" if i % 2 else "b", "p": 0.9 if i % 2 else 0.4, "ms": 5.0}
            for i, q in enumerate(qids)}
    coop = {q: {**aito[q], "pred": "a", "in": 100, "out": 10, "usd": 0.0001, "ms": 900.0} for q in qids}
    right = summarize.gated(aito, coop, qids, 0.5)
    assert all(right)   # sure ones from Aito (right), unsure ones from the LLM (right here)
    assert summarize.gated(aito, coop, qids, 0.3).count(True) == 10   # everything from Aito


def test_clinc150_is_pinned_and_sampled_like_banking77(monkeypatch):
    import importlib
    monkeypatch.setenv("BENCH_DATASET", "clinc150")
    c = importlib.reload(common)
    try:
        if not all((c.DATA / n).exists() for n in c.SHA256):
            pytest.skip("CLINC150 not fetched")
        train, test, dropped = c.split()
        assert (len(train), len(test), dropped, len(c.labels(train))) == (15000, 4498, 2, 150)
        s = c.sample(test)
        assert len(s) == 600 and c.RESULTS.name == "clinc150"
    finally:
        monkeypatch.delenv("BENCH_DATASET")
        importlib.reload(common)


def test_the_gate_rule_is_read_from_the_frozen_file():
    import summarize
    rule = json.loads((B / "gate_rule.json").read_text())
    assert summarize.THRESHOLDS == rule["thresholds"] and rule["split_seed"] == 77


def test_the_published_gate_flags_match_how_each_gate_was_decided():
    b77 = json.loads((B / "results" / "banking77.json").read_text())["gated"]
    assert b77["aito_then_shortlist_llm.gpt-5.4"]["planned"] is True
    assert b77["aito_then_rag_llm.gpt-5.4"]["planned"] is False       # found after the first results
    clinc = B / "results" / "clinc150" / "clinc150.json"
    if clinc.exists():
        g = json.loads(clinc.read_text())["gated"]["aito_then_rag_llm.gpt-5.4"]
        assert g["planned"] is True and g["preregistered"]["commit"] == "f49c5062"


def test_a_content_filter_error_does_not_change_the_settings_for_later_calls(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from openai import BadRequestError
    import llm

    def bad(msg):
        return BadRequestError(msg, response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)

    seen = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    seen.append({k: v for k, v in kw.items() if k not in ("model", "messages", "response_format")})
                    if "filtered" in kw["messages"][1]["content"]:
                        raise bad("The response was filtered due to the prompt triggering content management policy")
                    if "reasoning_effort" in kw:
                        raise bad("Unsupported parameter: 'reasoning_effort'")
                    msg = SimpleNamespace(content='{"intent": "a"}')
                    return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))

    monkeypatch.setattr(llm, "_client", lambda: _Client)
    monkeypatch.setattr(llm, "_settled", {})
    r = llm.ask("m", "s", "hello")                      # unsupported setting: falls back, and records it
    assert r["params"] == {"max_completion_tokens": 1500}
    with pytest.raises(BadRequestError):
        llm.ask("m2", "s", "filtered text")             # a content filter fails the call, it does not fall back
    assert llm._settled == {"m": {"max_completion_tokens": 1500}}


def test_endpoints_are_recorded_per_arm_and_never_relabel_other_arms(tmp_path):
    import run
    f = tmp_path / "endpoints.json"
    f.write_text(json.dumps({"aito": "shared.aito.ai, Aito v2", "llm": "Azure OpenAI, sweden"}))   # an older record
    run.record_endpoints(f, "llm_zero.gpt-9", {"aito": None, "llm": "OpenAI"})                     # an outsider's LLM-only run
    saved = json.loads(f.read_text())
    assert saved["per_arm"] == {"llm_zero.gpt-9": {"llm": "OpenAI"}}
    assert saved["aito"] == "shared.aito.ai, Aito v2"       # the recorded runs' endpoints are untouched
    assert run.uses("aito") == {"aito"} and run.uses("aito_llm.m") == {"aito", "llm"} and run.uses("llm_rag.m") == {"llm"}
