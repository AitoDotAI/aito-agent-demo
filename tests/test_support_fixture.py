"""The `support` fixture plants what its README claims, and nothing it doesn't.

Generates into a temp dir and measures with lifts.py, exactly as a reviewer
would. The control (channel has no effect on nps_after) is the check that the
measurement itself can come out null, and one test plants a channel effect to
prove the control check fails when it should."""

import hashlib
import json
import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts" / "support_fixture"))
import generate  # noqa: E402
import lifts  # noqa: E402

#: The fixture as loaded. A change to generate.py or to seed_company.py (which the
#: customer links replay) changes these: re-run lifts.py, re-check the README and
#: the "identical to shared" replay, then update the hashes on purpose.
PINNED = {
    "kb_articles.json": "bf591f2023f950b8caa2d37f0827d1404abcc15a3a48e1b3f2958e3c59249271",
    "support_tickets.json": "e050cb05051b6f7ccc4a2c912ddc6b5ebf57849a2e549be08c226ee585ea504c",
    "support_steps.json": "9fc655e4fd3339b81a510c8374c04be7964063de5398ba267958bb6645016588",
}


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("support")
    generate.main(d)
    return d, lifts.main(d)


def test_the_generated_files_are_the_pinned_ones(measured):
    d, _ = measured
    for name, digest in PINNED.items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == digest, name


def test_the_control_is_null(measured):
    _, m = measured
    assert m["control_holds"]
    assert all(abs(v["z_vs_rest"]) < 1.96 for v in m["control_channel"].values())


def test_the_control_check_fails_when_channel_does_matter(tmp_path):
    customers, usage = generate.northwind()
    kb = generate.build_kb()
    tickets, steps = generate.build_tickets(random.Random(generate.SEED), customers, usage, kb, control_leak=0.07)
    (tmp_path / "support_tickets.json").write_text(json.dumps(tickets))
    (tmp_path / "support_steps.json").write_text(json.dumps(steps))
    m = lifts.main(tmp_path)
    assert not m["control_holds"]
    assert m["control_channel"]["chat"]["z_vs_rest"] > 1.96


def test_every_planted_effect_is_there(measured):
    _, m = measured
    assert m["category_words"]["perfect_words"] == 0            # no word is a free rule
    p = m["priority_high"]
    assert lifts.differs(p["urgent_words"], p["no_urgent_words"])
    assert p["plan_differs"] and p["category_differs"]
    drift = m["drift_sso"]
    assert drift["before"]["p"] < 0.05 and drift["after"]["ci95"][0] > 0.6
    d = m["detractor"]
    for k in ("repeat_30d", "first_response_>24h", "health_red"):
        assert d[k]["ci95"][0] > d["base"]["ci95"][1], k
    lever = m["recovery_by_size"]
    assert {s: v["best"] for s, v in lever.items()} == {
        "SMB": "apology_credit", "Mid-market": "priority_callback", "Enterprise": "csm_outreach"}
    assert all(v["best_beats_none"] for v in lever.values())
    u = m["upsell"]
    assert lifts.differs(u["adoption_band_high"], u["adoption_band_low"])
    assert u["health_red"]["ci95"][1] < 0.06
    done = [x for x in m["next_step"] if x["next"] == "done"]
    assert done and all(x["p"] == 1.0 for x in done)


def test_the_readme_quotes_the_measured_numbers(measured):
    _, m = measured
    readme = (HERE.parent / "scripts" / "support_fixture" / "README.md").read_text()
    f = lambda x: f"{x:.2f}"  # noqa: E731
    quoted = [f(m["priority_high"]["urgent_words"]["p"]), f(m["priority_high"]["no_urgent_words"]["p"]),
              f(m["drift_sso"]["after"]["p"]), f(m["drift_sso"]["all_access_after"]["p"]),
              f(m["detractor"]["base"]["p"]), f(m["upsell"]["adoption_band_high"]["p"]),
              f(m["upsell"]["adoption_band_low"]["p"])]
    for size in ("SMB", "Mid-market", "Enterprise"):
        v = m["recovery_by_size"][size]
        quoted += [f(v[v["best"]]["p"]), f(v["none"]["p"])]
    missing = [q for q in quoted if q not in readme]
    assert not missing, f"README does not quote {missing}: re-run lifts.py and update it"
