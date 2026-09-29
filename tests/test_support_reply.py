"""The support reply: Aito's gate picks the path, code guards pick send or review.
A fake LLM, so nothing is called."""

import json
from types import SimpleNamespace

import pytest

from src import support_reply as R


class _FakeAgent:
    """Answers by which prompt it was sent (the routine writer or the unfamiliar read)."""

    def __init__(self, model, answers, asked):
        self.model, self.answers, self.asked, self.sent, self._extra = model, answers, asked, None, {}
        self._deployment = model

    def _param_sets(self):
        return [{}]

    def _create(self, base, extra):
        self.sent = base
        path = "routine" if base["messages"][0]["content"] == R._ROUTINE else "unfamiliar"
        self.asked.append((self.model, path))
        msg = SimpleNamespace(content=json.dumps(self.answers[path]))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=500, completion_tokens=120)), 900.0


def _env(gate="auto", resolution="sso_reconnect", recovery="csm_outreach"):
    step = lambda key, value, p=0.9, **kw: {"key": key, "value": value, "p": p, "alternatives": [], **kw}  # noqa: E731
    return {"ticket": {"ticket_id": "SUP-1", "text": "SSO login fails since this morning", "sender_domain": "acme1.example",
                       "channel": "email", "created_at": "2026-09-18T10:00"},
            "gate": gate,
            "steps": [step("customer", "CUS-1"), step("product", "PRD-sso"), step("category", "access"),
                      step("priority", "high"), step("resolution", resolution), step("kb", "KB-07g"),
                      step("similar", None, None, cases=[{"text": "SSO broke", "resolution": "sso_reconnect"}]),
                      step("first_step", "check_idp"), step("recovery", recovery)]}


KB = {"article_id": "KB-07g", "title": "Sso reconnect (guide)", "body": "check idp then reconnect sso."}
OPTIONS = ["refund", "sso_reconnect", "send_guide"]


@pytest.fixture
def llm(monkeypatch):
    """Answers per path; records which (model, path) was asked."""
    answers, asked, agents = {}, [], []

    def get(model=None):
        agents.append(_FakeAgent(model, answers, asked))
        return agents[-1]
    monkeypatch.setattr(R, "get_agent", get)
    return answers, asked


def test_a_sure_ticket_with_a_clean_draft_is_sent(llm):
    answers, asked = llm
    answers["routine"] = {"fits": True, "reply": "Hi, see KB-07g: check your IdP, then reconnect SSO."}
    d = R.draft_reply(_env(), KB, {"name": "Ana", "role": "it_admin"}, OPTIONS)
    assert (d["path"], d["send"], d["reasons"]) == ("routine", "auto", [])
    assert asked == [(R.ROUTINE_MODEL, "routine")] and d["tokens"] == 620


def test_an_unsure_ticket_goes_to_the_stronger_model_and_a_person(llm):
    answers, asked = llm
    answers["unfamiliar"] = {"reading": "wants SSO fixed", "resolution": "sso_reconnect",
                                   "reply": "Hi, we are looking into it.", "note": "confirm the IdP"}
    d = R.draft_reply(_env(gate="human"), KB, None, OPTIONS)
    assert (d["path"], d["send"], d["resolution"]) == ("unfamiliar", "review", "sso_reconnect")
    assert asked == [(R.UNFAMILIAR_MODEL, "unfamiliar")]


def test_a_confident_misread_is_caught_by_the_writer(llm):
    """Aito's gate said auto, the fast model says the facts don't fit: the ticket escalates."""
    answers, asked = llm
    answers["routine"] = {"fits": False, "why_not": "asks about the weather", "reply": ""}
    answers["unfamiliar"] = {"reading": "not a support request", "resolution": None,
                                   "reply": "Hi, could you tell us more?", "note": "off topic"}
    d = R.draft_reply(_env(), KB, None, OPTIONS)
    assert d["path"] == "unfamiliar" and d["send"] == "review"
    assert asked == [(R.ROUTINE_MODEL, "routine"), (R.UNFAMILIAR_MODEL, "unfamiliar")] and len(d["calls"]) == 2
    assert "asks about the weather" in d["reasons"][0]


def test_the_stronger_model_is_asked_only_on_request(llm):
    answers, asked = llm
    answers["unfamiliar"] = {"reading": "wants SSO fixed", "resolution": "sso_reconnect", "reply": "Hi.", "note": ""}
    d = R.draft_reply(_env(), KB, None, OPTIONS, stronger=True)
    assert asked == [(R.STRONG_MODEL, "unfamiliar")]
    assert (d["path"], d["model"], d["send"]) == ("unfamiliar", R.STRONG_MODEL, "review")
    assert d["usd"] is None  # no list price for it: none invented


def test_an_invented_resolution_is_dropped(llm):
    answers, _ = llm
    answers["unfamiliar"] = {"reading": "x", "resolution": "free_upgrade", "reply": "Hi.", "note": ""}
    assert R.draft_reply(_env(gate="assist"), KB, None, OPTIONS)["resolution"] is None


@pytest.mark.parametrize("reply, tripped", [
    ("We have issued a refund to your card.", "money"),
    ("As a goodwill gesture we'll credit your account.", "money"),
    ("This will be fixed within 24 hours.", "figures"),
    ("You get 20% off next month.", "money"),
    ("See KB-99z for details.", "article"),
    ("", "not empty"),
])
def test_guards_trip(reply, tripped):
    facts = R.facts_of(_env(), KB, None)
    bad = [g["name"] for g in R.guard(reply, facts) if not g["ok"]]
    assert tripped in bad


def test_guards_pass_a_clean_reply_and_a_credit_card():
    facts = R.facts_of(_env(), KB, None)
    assert all(g["ok"] for g in R.guard("Please update your credit card via KB-07g.", facts))


def test_money_is_allowed_when_decided_but_still_needs_a_person(llm):
    answers, _ = llm
    answers["routine"] = {"fits": True, "reply": "Hi, we have refunded the duplicate charge."}
    d = R.draft_reply(_env(resolution="refund"), KB, None, OPTIONS)
    assert all(g["ok"] for g in d["guards"]) and d["send"] == "review"
    assert "it moves money, so a person approves it" in d["reasons"]


def test_the_prompt_carries_the_decided_facts(monkeypatch):
    answers, asked, agents = {"routine": {"fits": True, "reply": "Hi."}}, [], []
    monkeypatch.setattr(R, "get_agent", lambda m=None: agents.append(_FakeAgent(m, answers, asked)) or agents[-1])
    R.draft_reply(_env(), KB, None, OPTIONS)
    prompt = agents[0].sent["messages"][1]["content"]
    assert "resolution: sso reconnect" in prompt and "KB-07g" in prompt
    assert "customer success manager" in prompt  # the csm_outreach recovery, in words
