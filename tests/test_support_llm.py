"""The support agent's LLM step: it may only answer with allowed labels, sees
Aito's shortlist when given one, and reports its token use. A fake client, so
no LLM is called."""

import json
from types import SimpleNamespace

from src import support_llm


class _FakeAgent:
    def __init__(self, answer):
        self.answer, self.sent, self._extra = answer, None, {}
        self._deployment = "gpt-5-mini"

    def _param_sets(self):
        return [{}]

    def _create(self, base, extra):
        self.sent = base
        msg = SimpleNamespace(content=json.dumps(self.answer))
        usage = SimpleNamespace(prompt_tokens=300, completion_tokens=40)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage), 1234.0


OPTIONS = {"category": ["billing", "bug"], "priority": ["high", "normal", "low"]}


def test_only_allowed_values_survive(monkeypatch):
    fake = _FakeAgent({"category": "billing", "priority": "urgent!!"})
    monkeypatch.setattr(support_llm, "get_agent", lambda: fake)
    d = support_llm.decide({"text": "charged twice"}, {"contact role": "finance"}, OPTIONS)
    assert d.values == {"category": "billing", "priority": None}
    assert (d.input_tokens, d.output_tokens, d.latency_ms) == (300, 40, 1234.0)


def test_the_shortlist_reaches_the_prompt_with_its_probabilities(monkeypatch):
    fake = _FakeAgent({"category": "bug"})
    monkeypatch.setattr(support_llm, "get_agent", lambda: fake)
    support_llm.decide({"text": "500 error"}, {}, {"category": OPTIONS["category"]},
                       {"category": [("bug", 0.62), ("billing", 0.21)]})
    prompt = fake.sent["messages"][1]["content"]
    assert "history suggests: bug (0.62), billing (0.21)" in prompt
    assert "allowed: billing, bug" in prompt and fake.sent["response_format"] == {"type": "json_object"}


def test_rag_examples_reach_the_prompt(monkeypatch):
    fake = _FakeAgent({"category": "bug"})
    monkeypatch.setattr(support_llm, "get_agent", lambda: fake)
    support_llm.decide({"text": "500 error"}, {}, {"category": OPTIONS["category"]},
                       examples=['- "page throws 500" -> category bug'])
    prompt = fake.sent["messages"][1]["content"]
    assert "Similar past tickets, and how this desk decided them:" in prompt and "page throws 500" in prompt
