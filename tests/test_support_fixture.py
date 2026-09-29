"""The `support` fixture plants what its README claims, and nothing it doesn't.

Generates into a temp dir and measures with lifts.py, exactly as a reviewer
would. The control (channel has no effect on nps_after) is the check that the
measurement itself can come out null, and one test plants a channel effect to
prove the control check fails when it should."""

import hashlib
import json
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
    "support_contacts.json": "0d1a22a2990e14a0317cff50e33827a5630939d1c63b3cdbba8a8c1d9e47b96a",
    "support_tickets.json": "ff3039b2672a0722059a89dea139a8e9f4132d2c74468f8f0b7947d2259d6fa0",
    "support_steps.json": "9c9934e19d7aaa9d99176efa6961f561178e090576acf914ef5bd822f5337006",
    "incoming.json": "6ed86676d39d891304862e42d6f082f61b7f2ebbe98ba474409a0924893c3806",
}


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("support")
    generate.main(d, d / "incoming.json")  # never the committed src/data copy
    return d, lifts.main(d, d / "incoming.json")


def test_the_generated_files_are_the_pinned_ones(measured):
    d, _ = measured
    for name, digest in PINNED.items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == digest, name


def test_the_committed_incoming_queue_is_the_generated_one(measured):
    d, _ = measured
    committed = HERE.parent / "src" / "data" / "support_incoming.json"
    assert committed.read_bytes() == (d / "incoming.json").read_bytes()


def test_the_incoming_queue_is_never_loaded(measured):
    d, _ = measured
    loaded = json.loads((d / "support_tickets.json").read_text())
    held = json.loads((d / "incoming.json").read_text())
    ids = {t["ticket_id"] for t in held["tickets"]}
    assert len(ids) == generate.HOLDOUT and not ids & {t["ticket_id"] for t in loaded}
    assert {s["ticket"] for s in held["steps"]} <= ids
    assert min(t["created_at"] for t in held["tickets"]) >= max(t["created_at"] for t in loaded)


def test_the_control_is_null(measured):
    _, m = measured
    assert m["control_holds"]
    assert all(abs(v["z_vs_rest"]) < 1.96 for v in m["control_channel"].values())


def test_the_control_check_fails_when_channel_does_matter(tmp_path):
    kb, contacts, tickets, steps = generate.generate(control_leak=0.07)
    for name, rows in (("support_contacts", contacts), ("support_tickets", tickets), ("support_steps", steps)):
        (tmp_path / f"{name}.json").write_text(json.dumps(rows))
    m = lifts.main(tmp_path)
    assert not m["control_holds"]
    assert m["control_channel"]["chat"]["z_vs_rest"] > 1.96


def test_every_planted_effect_is_there(measured):
    _, m = measured
    who = m["who"]
    assert who["known_contact_share"] > 0.85 and who["domains_naming_one_account"] == who["domains"] == m["accounts"]
    assert m["category_words"]["perfect_words"] == 0            # no word is a free rule
    r = m["role_to_category"]
    assert lifts.differs(r["billing_from_finance"], r["billing_from_others"])
    assert lifts.differs(r["integration_from_developer"], r["integration_from_others"])
    rec = m["recurring_issue"]
    assert rec["mean_top_issue_share_per_account"] > 2 * rec["largest_issue_share_overall"]
    assert m["product"]["named_in_text"] > 0.7
    p = m["priority"]
    assert p["high_with_urgent_words"]["ci95"][0] > 0.8 and p["high_enterprise_bug"]["ci95"][0] > 0.8
    assert p["high_otherwise"]["ci95"][1] < 0.1 and p["low_how_to"]["ci95"][0] > 0.8
    drift = m["drift_sso"]
    assert drift["before"]["p"] < 0.05 and drift["after"]["ci95"][0] > 0.6
    d = m["detractor"]
    for k in ("repeat_same_issue_30d", "first_response_>24h", "health_red"):
        assert d[k]["ci95"][0] > d["base"]["ci95"][1], k
    lever = m["recovery_by_size"]
    assert {s: v["best"] for s, v in lever.items()} == {
        "SMB": "apology_credit", "Mid-market": "priority_callback", "Enterprise": "csm_outreach"}
    assert all(v["best_beats_none"] for v in lever.values())
    u = m["upsell"]
    assert lifts.differs(u["adoption_band_high"], u["adoption_band_low"])
    assert u["health_red"]["ci95"][1] < 0.08
    done = [x for x in m["next_step"] if x["next"] == "done"]
    assert done and all(x["p"] == 1.0 for x in done)


def test_the_readme_quotes_the_measured_numbers(measured):
    _, m = measured
    readme = (HERE.parent / "scripts" / "support_fixture" / "README.md").read_text()
    f = lambda x: f"{x:.2f}"  # noqa: E731
    r, p = m["role_to_category"], m["priority"]
    quoted = [f(r["billing_from_finance"]["p"]), f(r["billing_from_others"]["p"]),
              f(p["high_with_urgent_words"]["p"]), f(p["high_otherwise"]["p"]),
              f(m["drift_sso"]["after"]["p"]), f(m["drift_sso"]["all_access_after"]["p"]),
              f(m["detractor"]["base"]["p"]), f(m["upsell"]["adoption_band_high"]["p"]),
              f(m["upsell"]["adoption_band_low"]["p"]), f(m["recurring_issue"]["mean_top_issue_share_per_account"])]
    for size in ("SMB", "Mid-market", "Enterprise"):
        v = m["recovery_by_size"][size]
        quoted += [f(v[v["best"]]["p"]), f(v["none"]["p"])]
    missing = [q for q in quoted if q not in readme]
    assert not missing, f"README does not quote {missing}: re-run lifts.py and update it"
