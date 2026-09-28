"""Agent output guards (CRO demo review 2026-09-28): a drafted email may only quote
figures a tool returned, and replies carry no em-dashes. Pure functions, no LLM."""

from src.agent_core import plain_dashes, ungrounded_figures

RECOMMEND = {"name": "recommend_outreach", "result": {
    "meeting_probability": 0.59, "baseline_meeting_probability": 0.16, "outcome_lift": 3.7}}


def test_a_figure_no_tool_returned_is_caught():
    draft = {"subject": "Quick idea", "body": "Teams like yours see ~70% more meetings."}
    assert ungrounded_figures(draft, [RECOMMEND], []) == ["70%"]


def test_figures_the_tool_returned_pass_in_any_quoted_form():
    draft = {"body": "About 59% vs a 16% baseline, 3.7x more meetings (3.7× lift)."}
    assert ungrounded_figures(draft, [RECOMMEND], []) == []


def test_an_earlier_turns_quoted_figure_still_counts():
    history = [{"role": "assistant", "content": "Win odds are 42% for this one."}]
    assert ungrounded_figures({"body": "a 42% win rate"}, [], history) == []


def test_numbers_that_are_not_claims_are_left_alone():
    assert ungrounded_figures({"body": "30 minutes on Tue 14 Oct, 2 case studies, 3x3 matrix"}, [], []) == []


def test_plain_dashes():
    assert plain_dashes("Warm intro — Case study") == "Warm intro, Case study"
    assert plain_dashes("low—risk") == "low-risk"
    assert plain_dashes("5–20 days") == "5–20 days"  # en-dash ranges stay
    assert plain_dashes(None) == ""


def test_a_returned_figure_matches_however_it_is_rounded():
    # live false positive: the tool returned outcome_lift 3.0 and the draft said "3.0x"
    trace = [{"result": {"outcome_lift": 3.0, "meeting_probability": 0.587}}]
    assert ungrounded_figures({"body": "3.0x, 3x, 59%, 58.7%"}, trace, []) == []
    assert ungrounded_figures({"body": "61%"}, trace, []) == ["61%"]


def test_enum_values_the_user_never_said_are_flagged():
    from src.agent_core import unstated_args
    from src.sales_agent import TOOLS
    spec = next(t for t in TOOLS if t["name"] == "win_odds")
    history = [{"role": "user", "content": "Existing Banking client wants a custom-dev project, sole-source."}]
    args = {"industry": "Banking", "relationship": "Existing client", "service_line": "Custom Dev",
            "competitive": "Sole-source", "client_size": "Enterprise", "complexity": "High"}
    assert unstated_args(args, spec, [], history) == {"client_size": "Enterprise", "complexity": "High"}
    # "a bank" still grounds Banking (a shared stem), and a tool's result is a source too
    history = [{"role": "user", "content": "A bank wants help."}]
    trace = [{"result": {"channel": "Warm intro"}}]
    assert unstated_args({"industry": "Banking"}, spec, trace, history) == {}
