#!/usr/bin/env python3
"""Live smoke of the deployed agent demo: every Aito-backed view, read-only.

    python scripts/live_smoke.py                       # https://agent.aito.ai
    python scripts/live_smoke.py --base http://localhost:8600

Fails when a view errors OR comes back hollow. Board td-20260929184223822327:
across the demos, handlers that turn an Aito error into an empty list let a
broken query look like "no data". Here `_relate_drivers` does exactly that
(src/app.py), so a failing _relate would read as "no driver above the lift
threshold" on every KPI. This asserts the views that visitors open are full.

Read-only and free: GETs only, and none of the LLM routes (resolve-llm, route,
the chats), which are billable. The demo's Aito key is read-only anyway.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

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


def check_resolve(body: dict) -> str:
    """A plain outage report must resolve to an intent, confidently, with reasons."""
    assert body.get("intent"), f"no intent resolved: {body}"
    assert (body.get("intent_p") or 0) >= 0.5, f"intent {body['intent']} at only {body.get('intent_p')}"
    assert body.get("why"), "the intent comes with no $why"
    return f"{body['intent']} ({body['intent_p']:.2f}), param {body.get('param_field')}={body.get('param')}"


def check_handoff(body: dict) -> str:
    counts = body.get("counts") or {}
    total = body.get("total") or 0
    assert total > 0, "nothing routed"
    assert sum(counts.values()) == total, f"routing counts {counts} don't add up to {total}"
    return f"{total} routed: {counts}"


def check_opportunity(body: dict) -> str:
    win = body.get("win") or {}
    assert 0 < (win.get("p") or 0) < 1, f"no win probability: {win.get('p')!r}"
    assert win.get("drivers"), "the win probability has no drivers"
    assert (body.get("effort_days") or 0) > 0, f"no effort estimate: {body.get('effort_days')!r}"
    assert body.get("references"), "no reference deals"
    return f"P(win) {win['p']:.2f}, {body['effort_days']} d, {len(body['references'])} references"


# _relate_drivers returns [] on an AitoError, so one KPI with no causes is
# plausible (a weak lift) but all of them empty is a broken _relate.
MIN_KPIS_WITH_CAUSES = 3


def check_company_360(body: dict) -> str:
    kpis = body.get("kpis") or []
    assert len(kpis) == 6, f"expected 6 KPIs, got {len(kpis)}"
    missing = [k.get("key") for k in kpis if k.get("current") is None]
    assert not missing, f"KPIs with no current value: {missing}"
    with_causes = [k.get("key") for k in kpis if k.get("causes")]
    assert len(with_causes) >= MIN_KPIS_WITH_CAUSES, (
        f"only {len(with_causes)} of 6 KPIs have causes ({with_causes}): a failing _relate reads as "
        "'no driver', see _relate_drivers")
    assert (body.get("customer") or {}).get("profile"), "no customer spotlight"
    return f"6 KPIs, {len(with_causes)} with causes"


def check_tools(body: dict) -> str:
    tools = body.get("tools") or []
    assert tools, "the agent has no tools"
    return f"{len(tools)} tools"


STEPS = [
    Step("health", "/api/health", check_health),
    Step("resolve", "/api/resolve", check_resolve,
         {"text": "My internet has been down since morning in Helsinki", "sender": ""}),
    Step("handoff", "/api/handoff", check_handoff),
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
    args = parser.parse_args()

    print(f"Agent live smoke — {args.base}, {len(STEPS)} views\n")
    failures = []
    for step in STEPS:
        started = time.monotonic()
        try:
            summary = step.check(fetch(args.base, step, args.timeout))
            elapsed = time.monotonic() - started
            print(f"  {'SLOW' if elapsed > SLOW_SECONDS else 'ok  '}  {step.name:<24} {summary}  ({elapsed:.1f}s)")
        except Exception as exc:   # noqa: BLE001 -- a smoke records every failure and walks on
            # (RemoteDisconnected, ConnectionResetError and ssl.SSLError are OSErrors, not URLErrors)
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((step.name, reason))
            print(f"  FAIL  {step.name:<24} {reason}  ({time.monotonic() - started:.1f}s)")

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
