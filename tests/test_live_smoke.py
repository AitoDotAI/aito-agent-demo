"""The live smoke's content checks (scripts/live_smoke.py), offline."""
import importlib.util
import sys
from pathlib import Path

import pytest

from src.gates import ASSIST_GATE, AUTO_GATE

_spec = importlib.util.spec_from_file_location(
    "live_smoke", Path(__file__).resolve().parents[1] / "scripts" / "live_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["live_smoke"] = smoke          # @dataclass looks its module up here
_spec.loader.exec_module(smoke)


def _kpi(key, causes):
    return {"key": key, "current": 0.5, "causes": [{"f": "x"}] * causes}


def _c360(causes_per_kpi):
    keys = ["conversion", "churn", "nps", "csat", "adoption", "ontime"]
    return {"kpis": [_kpi(k, c) for k, c in zip(keys, causes_per_kpi)],
            "customer": {"profile": {"id": "c1"}}}


def test_degraded_names_the_failure():
    body = {**_c360([1, 3, 1, 2, 1, 0]), "degraded": ["causes:ontime"]}
    with pytest.raises(AssertionError, match="causes:ontime"):
        smoke.check_company_360(body)
    assert "nothing degraded" in smoke.check_company_360({**_c360([1, 0, 0, 0, 0, 0]), "degraded": []})
    with pytest.raises(AssertionError, match="backstop"):
        smoke.check_company_360({**_c360([0, 0, 0, 0, 0, 0]), "degraded": []})


def test_require_degraded_fails_a_build_without_the_field(monkeypatch):
    monkeypatch.setattr(smoke, "REQUIRE_DEGRADED", True)
    with pytest.raises(AssertionError, match="require-degraded"):
        smoke.check_company_360(_c360([1, 3, 1, 2, 1, 0]))


def test_company_360_tolerates_a_kpi_without_causes():
    # 29.9: ontime 0 causes (a weak lift is plausible), the others filled
    assert "5 with causes" in smoke.check_company_360(_c360([1, 3, 1, 2, 1, 0]))


def test_company_360_fails_when_relate_is_silently_broken():
    # _relate_drivers returns [] on an AitoError: all-empty is the failure it hides
    with pytest.raises(AssertionError, match="_relate"):
        smoke.check_company_360(_c360([0, 0, 0, 0, 1, 0]))


def test_resolve_needs_a_confident_intent_with_reasons():
    with pytest.raises(AssertionError, match="no \\$why"):
        smoke.check_resolve({"intent": "check_outage", "intent_p": 0.98, "why": []})
    assert "check_outage" in smoke.check_resolve(
        {"intent": "check_outage", "intent_p": 0.98, "why": [{"x": 1}], "param_field": "location", "param": "Helsinki"})


def test_handoff_counts_must_add_up():
    with pytest.raises(AssertionError, match="add up"):
        smoke.check_handoff({"total": 10, "counts": {"auto": 7, "assist": 0, "handoff": 2}})


def test_no_llm_route_is_called():
    # the app's own list of billable LLM routes, so a new one is covered automatically;
    # /api/route also calls the LLM and is being added to _LLM_PATHS separately
    # read from the source: importing src.app needs Aito credentials
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" / "app.py").read_text())
    llm_paths = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                     if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "_LLM_PATHS" for t in n.targets))
    assert "/api/resolve-llm" in llm_paths      # guards against reading the wrong assignment
    assert "/api/route" in llm_paths            # #23: the route that calls the LLM is listed too
    forbidden = set(llm_paths)
    assert not {s.path for s in smoke.STEPS} & forbidden


def test_a_dropped_connection_is_a_recorded_failure_not_a_crash(monkeypatch, capsys):
    import http.client

    def urlopen(req, timeout):
        raise http.client.RemoteDisconnected("Remote end closed connection without response")
    monkeypatch.setattr(smoke.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(smoke.sys, "argv", ["live_smoke.py", "--base", "http://x"])
    assert smoke.main() == 1
    out = capsys.readouterr().out
    assert f"{len(smoke.STEPS)} of {len(smoke.STEPS)} views FAILED" in out


def test_every_step_is_a_get(monkeypatch):
    methods = []

    class _Res:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def urlopen(req, timeout):
        methods.append(req.get_method())
        return _Res()
    monkeypatch.setattr(smoke.urllib.request, "urlopen", urlopen)
    for step in smoke.STEPS:
        smoke.fetch("http://x", step, 1)
    assert set(methods) == {"GET"} and len(methods) == len(smoke.STEPS)


# ── the band, not the label (td-20260919195009050217) ──────────────────────
# Every test below nudges one fixture across a gate and changes nothing else:
# same predicted label, same $why, same counts-that-add-up. That is the shape of
# the drift the old checks could not see.


def _resolved(p):
    """A resolve body that differs from a passing one only in its $p."""
    return {"intent": "check_outage", "intent_p": p, "why": [{"x": 1}],
            "param_field": "location", "param": "Helsinki"}


def test_resolve_crossing_the_auto_gate_fails_though_the_label_is_the_same():
    over = smoke.check_resolve(_resolved(AUTO_GATE + 0.0011))
    assert "auto" in over and "+0.0011 from the auto gate" in over
    under = _resolved(AUTO_GATE - 0.0011)
    with pytest.raises(AssertionError, match="is band 'assist', not 'auto'"):
        smoke.check_resolve(under)
    # what the old check asserted still holds on the failing body: label, $why, >= 0.5
    assert under["intent"] == "check_outage" and under["why"] and under["intent_p"] >= 0.5


def test_resolve_below_the_assist_gate_fails_too():
    with pytest.raises(AssertionError, match="is band 'handoff', not 'auto'"):
        smoke.check_resolve(_resolved(ASSIST_GATE - 0.0011))


#: what a live /api/handoff reports for the queue's closest-to-flipping row
_MARGIN = {"delta": 0.0498, "gate": "auto", "band": "auto", "text": "Nothing has worked..."}


def _handoff(counts, rows=(), **extra):
    """A handoff body shaped like the live one, so each test breaks one thing.
    Pass margin=None for a build from before that field shipped."""
    return {"total": sum(counts.values()), "counts": dict(counts), "handoff": list(rows),
            "margin": dict(_MARGIN), **extra}


def test_one_ticket_crossing_a_gate_fails_the_handoff_check():
    assert "routed" in smoke.check_handoff(_handoff(smoke.EXPECTED_BANDS))
    flipped = dict(smoke.EXPECTED_BANDS, auto=smoke.EXPECTED_BANDS["auto"] - 1,
                   assist=smoke.EXPECTED_BANDS["assist"] + 1)
    body = _handoff(flipped)
    assert sum(body["counts"].values()) == body["total"]      # the old check's only assertion
    with pytest.raises(AssertionError, match="crossed a confidence gate"):
        smoke.check_handoff(body)


def test_the_whole_queue_in_one_band_fails():
    total = sum(smoke.EXPECTED_BANDS.values())
    with pytest.raises(AssertionError, match="band split is"):
        smoke.check_handoff(_handoff({"auto": 0, "assist": 0, "handoff": total}))


def _row(p, reason, text="a ticket"):
    return {"text": text, "intent": "refund", "p": p, "reason": reason}


def test_a_handoff_row_must_be_one_for_the_reason_it_gives():
    sensitive = "sensitive action (refund), needs human verification"
    assert "routed" in smoke.check_handoff(
        _handoff(smoke.EXPECTED_BANDS, [_row(0.754, sensitive)]))
    # the same row a thousandth under the assist gate: still handed off, but the
    # visitor is told "sensitive" when the code would have said "low confidence"
    with pytest.raises(AssertionError, match="not the reason the code used"):
        smoke.check_handoff(_handoff(smoke.EXPECTED_BANDS,
                                     [_row(ASSIST_GATE - 0.0011, sensitive)]))


def test_a_row_listed_as_a_handoff_that_the_gates_would_serve_fails():
    with pytest.raises(AssertionError, match="but the gates put it in 'auto'"):
        smoke.check_handoff(_handoff(smoke.EXPECTED_BANDS,
                                     [_row(0.95, "low confidence (95%), Aito won't guess on this")]))


def test_the_margin_is_required_by_default_and_reported(monkeypatch):
    # the field has been live since 2026-11-06, so a build without it is a failure
    with pytest.raises(AssertionError, match="rolled back"):
        smoke.check_handoff(_handoff(smoke.EXPECTED_BANDS, margin=None))
    served = _handoff(smoke.EXPECTED_BANDS,
                      margin={"delta": 0.0011, "gate": "auto", "band": "auto", "text": "a hair over"})
    assert "+0.0011 from the auto gate" in smoke.check_handoff(served)
    # --no-require-margin checks the rest against an older build instead of refusing it
    monkeypatch.setattr(smoke, "REQUIRE_MARGIN", False)
    assert "no `margin`" in smoke.check_handoff(_handoff(smoke.EXPECTED_BANDS, margin=None))


def test_the_gates_come_from_the_app_not_from_this_script():
    from src import gates
    assert (smoke.AUTO_GATE, smoke.ASSIST_GATE) == (gates.AUTO_GATE, gates.ASSIST_GATE)
    assert smoke.band_of is gates.band_of


# ── the two surfaces the band gate did not reach (follow-up to #47) ────────


def _envelope(**over):
    """An envelope body that passes, so each test can break exactly one thing."""
    body = {"ticket": {"ticket_id": smoke.ENVELOPE_TICKET}, "gate": smoke.ENVELOPE_BAND,
            "degraded": [],
            "steps": [{"key": "customer", "value": "ACC-1", "p": None},
                      {"key": "priority", "value": "normal", "p": 0.797},
                      {"key": "resolution", "value": "api_guidance", "p": 0.984, "gate": "auto"}]}
    return {**body, **over}


def test_the_envelope_is_checked_on_the_ticket_the_page_opens():
    out = smoke.check_envelope(_envelope())
    assert smoke.ENVELOPE_TICKET in out and "band auto" in out and "from the auto gate" in out
    with pytest.raises(AssertionError, match="fixture was reordered"):
        smoke.check_envelope(_envelope(ticket={"ticket_id": "SUP-00000"}))


def test_the_envelope_band_is_asserted_not_just_its_steps():
    steps = [{"key": "resolution", "value": "api_guidance", "p": 0.80, "gate": "assist"}]
    with pytest.raises(AssertionError, match="decides this ticket differently"):
        smoke.check_envelope(_envelope(gate="assist", steps=steps))


def test_an_envelope_band_that_contradicts_its_own_p_fails():
    # the band says auto, the $p it is supposed to come from is an assist
    steps = [{"key": "resolution", "value": "api_guidance", "p": 0.80, "gate": "auto"}]
    with pytest.raises(AssertionError, match="by the app's own gates"):
        smoke.check_envelope(_envelope(steps=steps))


def test_an_envelope_with_a_failed_step_or_no_p_fails():
    with pytest.raises(AssertionError, match="Aito failed behind"):
        smoke.check_envelope(_envelope(degraded=["resolution"]))
    with pytest.raises(AssertionError, match="nothing decides the band"):
        smoke.check_envelope(_envelope(steps=[{"key": "resolution", "value": None, "p": None}]))


def test_the_resolve_samples_are_read_from_the_page_itself():
    samples = smoke.page_samples()
    assert len(samples) >= 5
    labels = [label for label, _, _ in samples]
    assert "Outage · Helsinki" in labels and "Balance" in labels
    for label, text, sender in samples:
        assert text and sender, (label, text, sender)      # the page sends a sender; so must the gate
        assert label in smoke.SAMPLE_BANDS, f"{label}: a new sample needs its band stated"


def test_every_sample_is_a_step_with_its_own_sender():
    by_text = {s.params["text"]: s for s in smoke.STEPS if s.path == "/api/resolve" and s.params}
    for label, text, sender in smoke.page_samples():
        assert text in by_text, f"{label} is offered by the page but not gated"
        assert by_text[text].params["sender"] == sender, label
    # the no-sender case stays: a visitor typing free text sends none
    assert any(s.params.get("sender") == "" for s in smoke.STEPS if s.path == "/api/resolve")
    assert any(s.path == "/api/support/envelope" for s in smoke.STEPS)


def test_a_sample_with_no_stated_band_is_not_assumed_to_be_auto(monkeypatch):
    monkeypatch.setattr(smoke, "SAMPLE_BANDS", {"Balance": "auto"})
    with pytest.raises(AssertionError, match="needs its band stated"):
        smoke.sample_band("Outage · Helsinki")
