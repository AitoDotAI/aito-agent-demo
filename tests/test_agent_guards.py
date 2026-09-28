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


# ── review findings (PR #11): each case below was a live miss or a false block ──

def _win_odds_spec():
    from src.sales_agent import TOOLS
    return next(t for t in TOOLS if t["name"] == "win_odds")


def _unstated(args, said, trace=()):
    from src.agent_core import unstated_args
    return unstated_args(args, _win_odds_spec(), list(trace), [{"role": "user", "content": said}])


def test_a_guards_own_message_never_grounds_the_retry():
    rejected = [{"result": {"error": "not queued: 70% did not come from a tool."}}]
    assert ungrounded_figures({"body": "~70% more meetings"}, rejected, []) == ["70%"]
    annotated = [{"result": {"win_probability": 0.6,
                             "ignored_unstated_fields": {"client_size": "Enterprise"}}}]
    assert _unstated({"client_size": "Enterprise"}, "A bank.", annotated) == {"client_size": "Enterprise"}


def test_near_misses_do_not_count_as_said():
    assert _unstated({"deal_size_band": "M"}, "I'm keen, it's a bank") == {"deal_size_band": "M"}
    assert _unstated({"lead_source": "Partner"}, "it is part of a programme") == {"lead_source": "Partner"}
    assert _unstated({"lead_source": "Event"}, "they will eventually buy") == {"lead_source": "Event"}
    assert _unstated({"complexity": "High"}, "a highly regulated bank") == {"complexity": "High"}


def test_the_ways_a_rep_actually_says_a_value_count():
    cases = [({"industry": "Telecom"}, "a telco wants help"),
             ({"client_size": "Mid-market"}, "a mid-size retailer"),
             ({"service_line": "Custom Dev"}, "custom development for a bank"),
             ({"service_line": "Analytics & ML"}, "an analytics project"),
             ({"relationship": "New logo"}, "a new client in retail"),
             ({"industry": "Logistics"}, "a logistic company"),
             ({"deal_size_band": "L"}, "an L deal, sole-source")]
    for args, said in cases:
        assert _unstated(args, said) == {}, (args, said)


def test_figures_must_match_closely_and_counts_are_not_claims():
    lift = [{"result": {"outcome_lift": 3.7, "meeting_probability": 0.59}}]
    assert ungrounded_figures({"body": "3.3x more meetings"}, lift, []) == ["3.3x"]
    assert ungrounded_figures({"body": "1x the baseline"}, lift, []) == ["1x"]  # not grounded by p=0.59
    assert ungrounded_figures({"body": "two calls, 2 x 30 min"}, lift, []) == []


def test_odd_model_output_does_not_crash_the_guards():
    from src.agent_core import _safe_args
    assert _safe_args("[]") == {} and _safe_args("null") == {} and _safe_args("{bad") == {}
    assert ungrounded_figures({"body": "59%"}, [], [{"role": "assistant", "content": None}]) == ["59%"]
    from src.agent_core import unstated_args
    assert unstated_args({"industry": "Banking"}, _win_odds_spec(), [],
                         [{"role": "user", "content": None}]) == {"industry": "Banking"}


def test_a_returned_value_grounds_only_its_own_field():
    # live: recommend_outreach returned personalization "High", and complexity "High" rode on it
    trace = [{"result": {"personalization": "High", "channel": "Warm intro",
                         "drivers": [{"field": "competitive", "value": "Competitive", "lift": 0.9}]}}]
    assert _unstated({"complexity": "High"}, "a bank", trace) == {"complexity": "High"}
    assert _unstated({"competitive": "Competitive"}, "a bank", trace) == {}
    trace = [{"result": {"client_industry": "Banking"}}]
    assert _unstated({"industry": "Banking"}, "this one", trace) == {}
