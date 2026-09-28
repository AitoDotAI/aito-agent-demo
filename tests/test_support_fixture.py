"""The `support` fixture plants what its README claims, and nothing it doesn't.

Generates into a temp dir and measures with lifts.py, exactly as a reviewer
would. The control (channel has no effect on nps_after) is the check that the
measurement itself can come out null."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "support_fixture"))
import generate  # noqa: E402
import lifts  # noqa: E402


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("support")
    generate.main(d)
    return d, lifts.main(d)


def test_generation_is_deterministic(measured, tmp_path):
    d, _ = measured
    generate.main(tmp_path)
    for f in ("kb_articles.json", "support_tickets.json", "support_steps.json"):
        assert (tmp_path / f).read_bytes() == (d / f).read_bytes(), f


def test_the_control_is_null(measured):
    _, m = measured
    assert m["control_holds"]
    assert all(0.9 <= v["lift"] <= 1.1 for v in m["control_channel"].values())


def test_every_planted_effect_is_there(measured):
    _, m = measured
    assert m["category_words"]["perfect_words"] == 0            # no word is a free rule
    p = m["priority_high"]
    assert p["urgent_words"]["ci95"][0] > p["no_urgent_words"]["ci95"][1]
    drift = m["drift_sso"]
    assert drift["before"]["p"] < 0.05 and drift["after"]["p"] > 0.6
    d = m["detractor"]
    for k in ("repeat_30d", "first_response_>24h", "health_red"):
        assert d[k]["ci95"][0] > d["base"]["p"], k
    assert {s: v["best"] for s, v in m["recovery_by_size"].items()} == {
        "SMB": "apology_credit", "Mid-market": "priority_callback", "Enterprise": "csm_outreach"}
    u = m["upsell"]
    assert u["high_adoption_>=0.67"]["ci95"][0] > u["low_adoption_<0.34"]["ci95"][1]
    assert u["health_red"]["p"] < 0.05
    assert all(x["p"] > 0.4 for x in m["next_step"])
