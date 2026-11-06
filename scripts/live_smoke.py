#!/usr/bin/env python3
"""Live smoke of the deployed agent demo: every Aito-backed view, read-only.

    python scripts/live_smoke.py                       # https://agent.aito.ai
    python scripts/live_smoke.py --base http://localhost:8600

Fails when a view errors OR comes back hollow. Board td-20260929184223822327:
across the demos, handlers that turn an Aito error into an empty list let a
broken query look like "no data". Here `_relate_drivers` does exactly that
(src/app.py), so a failing _relate would read as "no driver above the lift
threshold" on every KPI. This asserts the views that visitors open are full.

Also fails when a view's *band* changed while its predicted label did not. Board
td-20260919195009050217: these checks asserted the label and a 0.5 floor the app
uses for nothing, so a $p drifting across AUTO_GATE (0.85) or ASSIST_GATE (0.65)
silently moved a ticket between "served as is", "the LLM helps" and "a person
decides" with the smoke green. The band is what a visitor sees happen, so the
band is what is asserted, and the distance to the deciding gate is printed.

Read-only and free: GETs only, and none of the LLM routes (resolve-llm, route,
the chats), which are billable. The demo's Aito key is read-only anyway.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# The app's own gates and band logic, imported rather than re-spelled: a gate
# script that keeps its own copy of 0.85 is exactly how the band it asserts
# drifts away from the band the demo serves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.gates import ASSIST_GATE, AUTO_GATE, band_of, margin_to_gate  # noqa: E402

LIVE_BASE = "https://agent.aito.ai"
SLOW_SECONDS = 20.0


@dataclass
class Step:
    name: str
    path: str
    check: Callable[[Any], str]
    params: dict | None = None


def check_health(body: dict) -> str:
    assert body.get("aito_connected") is True, f"server cannot reach Aito: {body}"
    return "Aito reachable"


#: the band /api/resolve's sample ticket has to land in. The page's whole claim is
#: that a plain, unambiguous outage report is resolved and served as is; at `assist`
#: the same screen would be saying the LLM has to help with this one.
RESOLVE_BAND = "auto"


#: the sample tickets the Support resolution page offers, read out of the page
#: itself so a new sample is gated the moment it is added and the two cannot
#: drift apart. The page sends the sample's `sender`; so does the gate.
_SAMPLE_RE = re.compile(r'\{\s*label:\s*"([^"]+)",\s*text:\s*"([^"]*)",\s*sender:\s*"([^"]*)"\s*\}')


def page_samples() -> list[tuple[str, str, str]]:
    src = (Path(__file__).resolve().parents[1] / "frontend" / "components" / "AppShell.tsx").read_text()
    block = src[src.index("const SAMPLES"):]
    found = _SAMPLE_RE.findall(block[:block.index("];")])
    assert found, "cannot read SAMPLES out of AppShell.tsx: the gate would be checking nothing"
    return found


#: the band each offered sample has to land in. A sample missing here is NOT
#: assumed to be `auto` — the band is the behaviour, so the page's claim about a
#: new sample has to be stated rather than inherited.
SAMPLE_BANDS = {
    "Outage · Helsinki": "auto",
    "Repair · cracked screen": "auto",
    "Cancel · broadband": "auto",
    "Refund · roaming": "auto",
    "Balance": "auto",
}


def sample_band(label: str) -> str:
    assert label in SAMPLE_BANDS, (
        f"{label!r} is offered by the Support page but needs its band stated in SAMPLE_BANDS: "
        "say which of auto/assist/handoff the page claims for it")
    return SAMPLE_BANDS[label]


def check_resolve(body: dict, expected: str | None = None) -> str:
    """A plain outage report must resolve to an intent, confidently, with reasons —
    and land in the band the page is built to show.

    The floor here used to be 0.5, a number the app uses for nothing: anywhere
    between 0.5 and AUTO_GATE the demo's behaviour has already changed and this
    check stayed green, because the predicted label does not move when a $p
    crosses a gate (td-20260919195009050217).
    """
    assert body.get("intent"), f"no intent resolved: {body}"
    p = body.get("intent_p") or 0
    assert body.get("why"), "the intent comes with no $why"
    band = band_of(p)
    gate, delta = margin_to_gate(p)
    want = RESOLVE_BAND if expected is None else expected
    assert band == want, (
        f"intent {body['intent']} at $p {p:.4f} is band {band!r}, not {want!r} "
        f"({delta:+.4f} from the {gate} gate): the label is unchanged but the page "
        "now behaves differently")
    return (f"{body['intent']} ({p:.2f}, {band}, {delta:+.4f} from the {gate} gate), "
            f"param {body.get('param_field')}={body.get('param')}")


#: the band split the fixed 10-ticket queue produces, measured live on 2026-11-05
#: (agent.aito.ai, origin/main 1fea7f7a). Pinned because a band flip IS the change
#: this gate exists to catch: both the queue and the demo's data are fixed, so these
#: counts move only when a prediction crosses a gate — and then a visitor sees a
#: different page. When the move is legitimate (queue edited, data reloaded),
#: re-measure and say in the PR which row changed band and which way.
EXPECTED_BANDS = {"auto": 6, "assist": 1, "handoff": 3}
#: set by --require-margin: once the deployed build serves /api/handoff's `margin`,
#: its absence must fail rather than be tolerated (as with REQUIRE_DEGRADED below).
REQUIRE_MARGIN = False


def check_handoff(body: dict) -> str:
    """The queue is triaged the way the page claims, row by row.

    `counts` adding up was the whole check before, and every possible split adds
    up — all 10 in one band included. So this asserts the split itself, and that
    each row the page shows as a handoff is one for the reason it gives.
    """
    counts = body.get("counts") or {}
    total = body.get("total") or 0
    assert total > 0, "nothing routed"
    assert sum(counts.values()) == total, f"routing counts {counts} don't add up to {total}"
    assert counts == EXPECTED_BANDS, (
        f"band split is {counts}, expected {EXPECTED_BANDS}: a ticket crossed a confidence "
        "gate, so this queue is triaged differently than when the page was reviewed")
    for row in body.get("handoff") or []:
        p, reason = row.get("p") or 0, row.get("reason") or ""
        sensitive = "sensitive action" in reason
        assert band_of(p, sensitive) == "handoff", (
            f"row {row.get('text')!r} is in the handoff list at $p {p:.4f} with reason "
            f"{reason!r}, but the gates put it in {band_of(p, sensitive)!r}")
        if sensitive:
            # app.py tests low confidence FIRST, so a sensitive reason means the $p cleared
            # the assist gate — below it the row would read "low confidence" instead
            assert p >= ASSIST_GATE, (
                f"row {row.get('text')!r} hands off at $p {p:.4f} for a sensitive action, but "
                f"{p:.4f} is under the {ASSIST_GATE} assist gate: the reason the visitor reads "
                "is not the reason the code used")
    margin = body.get("margin")
    assert not (REQUIRE_MARGIN and margin is None), (
        "/api/handoff serves no `margin`, so how close this queue is to a different "
        "triage cannot be seen (--require-margin)")
    if margin is None:
        return f"{total} routed: {counts} (build serves no `margin`)"
    return (f"{total} routed: {counts}; closest to flipping: {margin.get('delta'):+.4f} from the "
            f"{margin.get('gate')} gate ({margin.get('band')}, {str(margin.get('text'))[:40]!r})")


def check_opportunity(body: dict) -> str:
    win = body.get("win") or {}
    assert 0 < (win.get("p") or 0) < 1, f"no win probability: {win.get('p')!r}"
    assert win.get("drivers"), "the win probability has no drivers"
    assert (body.get("effort_days") or 0) > 0, f"no effort estimate: {body.get('effort_days')!r}"
    assert body.get("references"), "no reference deals"
    return f"P(win) {win['p']:.2f}, {body['effort_days']} d, {len(body['references'])} references"


# Since #24, company-360 names what fell back to empty on an AitoError in
# `degraded` ("causes:<kpi>", "graph"), so a failure is reported, not inferred.
# A build from before #24 has no such field: then fall back to the old
# inference (one KPI with no causes is a plausible weak lift; most of them
# empty is a broken _relate).
MIN_KPIS_WITH_CAUSES_WITHOUT_DEGRADED = 3
# Set by --require-degraded: once the site serves `degraded`, its absence must
# fail rather than quietly revert to the inference above.
REQUIRE_DEGRADED = False


def check_company_360(body: dict) -> str:
    kpis = body.get("kpis") or []
    assert len(kpis) == 6, f"expected 6 KPIs, got {len(kpis)}"
    missing = [k.get("key") for k in kpis if k.get("current") is None]
    assert not missing, f"KPIs with no current value: {missing}"
    with_causes = [k.get("key") for k in kpis if k.get("causes")]
    assert (body.get("customer") or {}).get("profile"), "no customer spotlight"
    if "degraded" in body:
        assert body["degraded"] == [], f"Aito failed behind: {body['degraded']}"
        assert with_causes, "no KPI has causes (backstop)"
        return f"6 KPIs, {len(with_causes)} with causes, nothing degraded"
    assert not REQUIRE_DEGRADED, "company-360 has no `degraded` field (--require-degraded)"
    assert len(with_causes) >= MIN_KPIS_WITH_CAUSES_WITHOUT_DEGRADED, (
        f"only {len(with_causes)} of 6 KPIs have causes ({with_causes}): a failing _relate reads as "
        "'no driver' on a pre-#24 build (no `degraded` field)")
    return f"6 KPIs, {len(with_causes)} with causes (pre-#24 build: no `degraded` field)"


#: the ticket the Support envelope page opens by itself: EnvelopeView.tsx takes
#: tickets[0] from /api/support/incoming. The queue is a committed fixture, so a
#: different ticket here means the fixture was reordered, not that Aito moved.
ENVELOPE_TICKET = "SUP-11986"
#: the band that ticket's resolution step lands in, measured live 2026-11-06
ENVELOPE_BAND = "auto"
#: /api/support/envelope calls the bottom band "human" where /api/handoff says "handoff"
_ENVELOPE_NAME = {"auto": "auto", "assist": "assist", "handoff": "human"}


def check_envelope(body: dict) -> str:
    """The envelope page's one band: `gate`, decided by the resolution step's $p.

    Only that step is banded. priority, kb, risk, recovery and upsell come back
    with a $p but nothing is gated on them — risk and recovery are read against
    a base rate rather than decided — so the distance from a gate is reported
    for the $p that actually decides what the page does.
    """
    got = (body.get("ticket") or {}).get("ticket_id")
    assert got == ENVELOPE_TICKET, (
        f"the queue now opens on {got}, not {ENVELOPE_TICKET}: the incoming fixture was "
        "reordered, so this is no longer the ticket a visitor sees first")
    assert body.get("degraded") == [], f"Aito failed behind: {body.get('degraded')}"
    steps = {s.get("key"): s for s in body.get("steps") or []}
    assert steps, "the envelope has no steps"
    res = steps.get("resolution") or {}
    p = res.get("p")
    assert p is not None, "the resolution step came back with no $p, so nothing decides the band"
    served = body.get("gate")
    assert served == ENVELOPE_BAND, (
        f"the envelope serves band {served!r} at $p {p}, expected {ENVELOPE_BAND!r}: history "
        "decides this ticket differently than when the page was reviewed")
    assert served == _ENVELOPE_NAME[band_of(p)], (
        f"the envelope says {served!r} but $p {p} is {band_of(p)!r} by the app's own gates")
    gate, delta = margin_to_gate(p)
    answered = [s for s in steps.values() if s.get("p") is not None]
    return (f"{got}: {len(steps)} steps, {len(answered)} with a $p, band {served} "
            f"({res.get('value')} at {p}, {delta:+.4f} from the {gate} gate)")


def check_tools(body: dict) -> str:
    tools = body.get("tools") or []
    assert tools, "the agent has no tools"
    return f"{len(tools)} tools"


def _resolve_check(expected: str) -> Callable[[Any], str]:
    def check(body: dict) -> str:
        return check_resolve(body, expected)
    return check


STEPS = [
    Step("health", "/api/health", check_health),
    # free text with no sender: what a visitor who types their own message sends
    Step("resolve (typed, no sender)", "/api/resolve", check_resolve,
         {"text": "My internet has been down since morning in Helsinki", "sender": ""}),
    # and every sample the page offers, with the sender the page sends with it
    *[Step(f"resolve · {label}", "/api/resolve", _resolve_check(sample_band(label)),
           {"text": text, "sender": sender})
      for label, text, sender in page_samples()],
    Step("handoff", "/api/handoff", check_handoff),
    Step("support/envelope", "/api/support/envelope", check_envelope,
         {"ticket_id": ENVELOPE_TICKET}),
    Step("opportunity", "/api/opportunity", check_opportunity),
    Step("company-360 (SMB/Free)", "/api/company-360", check_company_360, {"size": "SMB", "plan": "Free"}),
    Step("company-360 (all)", "/api/company-360", check_company_360),
    Step("sales-agent/tools", "/api/sales-agent/tools", check_tools),
    Step("company-agent/tools", "/api/company-agent/tools", check_tools),
]


def fetch(base: str, step: Step, timeout: float) -> Any:
    url = base + step.path + ("?" + urllib.parse.urlencode(step.params) if step.params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "agent-live-smoke"}),
                                timeout=timeout) as res:
        return json.load(res)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default=LIVE_BASE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--require-degraded", action="store_true",
                        help="fail if company-360 lacks the `degraded` field (turn on once the "
                             "deployed build serves it)")
    parser.add_argument("--require-margin", action="store_true",
                        help="fail if handoff lacks the `margin` field (turn on once the "
                             "deployed build serves it)")
    args = parser.parse_args()
    global REQUIRE_DEGRADED, REQUIRE_MARGIN
    REQUIRE_DEGRADED = args.require_degraded
    REQUIRE_MARGIN = args.require_margin

    print(f"Agent live smoke — {args.base}, {len(STEPS)} views\n")
    failures = []
    for step in STEPS:
        started = time.monotonic()
        try:
            summary = step.check(fetch(args.base, step, args.timeout))
            elapsed = time.monotonic() - started
            print(f"  {'SLOW' if elapsed > SLOW_SECONDS else 'ok  '}  {step.name:<34} {summary}  ({elapsed:.1f}s)")
        except Exception as exc:   # noqa: BLE001 -- a smoke records every failure and walks on
            # (RemoteDisconnected, ConnectionResetError and ssl.SSLError are OSErrors, not URLErrors)
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((step.name, reason))
            print(f"  FAIL  {step.name:<34} {reason}  ({time.monotonic() - started:.1f}s)")

    print()
    if failures:
        print(f"{len(failures)} of {len(STEPS)} views FAILED:")
        for name, reason in failures:
            print(f"  {name}: {reason}")
        return 1
    print(f"All {len(STEPS)} views answered with content.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
