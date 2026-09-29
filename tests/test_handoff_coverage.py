"""The handoff tier's interim unfamiliar-wording check (until Aito ships its own
evidence-coverage signal): a confident $p on wording the log has barely seen must
still go to a person. Runs on a fake client in the live response shapes."""

import pytest
from fastapi.testclient import TestClient

from src import app as app_module

LOG = ["Is there a network outage in Helsinki?", "My screen is cracked", "refund the roaming charge please"]


class _Fake:
    def query(self, table, where=None, select=None, order_by=None, limit=5):
        return {"hits": [{"text": t} for t in LOG]}

    def predict(self, table, where, target, limit=5, select=None):
        text = where["text"].lower()
        intent = "refund" if "refund" in text else ("repair_help" if "screen" in text else "check_outage")
        return {"hits": [{"feature": intent, "$p": 0.98}, {"feature": "find_shop", "$p": 0.01}]}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(app_module, "aito", _Fake())
    monkeypatch.setattr(app_module, "_log_vocab", None)
    yield
    app_module._log_vocab = None


def test_coverage_is_the_share_of_content_words_seen_in_the_log(fake):
    assert app_module._coverage("Is there an outage in Helsinki?") == 1.0  # outage, helsinki
    assert app_module._coverage("What's the weather in Helsinki?") == 0.5  # weather unseen
    assert app_module._coverage("hello?") == 0.0  # no content words: nothing to go on


def test_unfamiliar_wording_goes_to_a_person_even_when_p_is_high(fake, monkeypatch):
    monkeypatch.setattr(app_module, "_HANDOFF_QUEUE", [
        "Is there a network outage in Helsinki?",     # familiar, confident -> auto
        "Same problem as last time",                  # unfamiliar, $p 0.98 -> a person
        "refund the roaming charge please",           # familiar but sensitive -> a person
    ])
    body = TestClient(app_module.app).get("/api/handoff").json()
    assert body["counts"] == {"auto": 1, "assist": 0, "handoff": 2}
    reasons = {h["text"]: h["reason"] for h in body["handoff"]}
    assert reasons["Same problem as last time"].startswith("unfamiliar wording")
    assert reasons["refund the roaming charge please"].startswith("sensitive action")
    assert all("coverage" in h for h in body["handoff"])
