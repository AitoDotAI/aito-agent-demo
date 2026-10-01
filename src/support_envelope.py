"""The support agent's predictive envelope (docs/design/support-agent.md, phase 1).

One incoming ticket, the steps a support agent takes, and the Aito op that
grounds each step. Read-only: tickets come from the held-out incoming queue
(src/data/support_incoming.json), which is never loaded into Aito, so every
prediction is on a ticket Aito has not seen and can be compared with the
ticket's recorded truth.

Every prediction goes through `guarded()`, which enforces the fixture's
inputs-vs-targets table (scripts/support_fixture/README.md) in code: a step
may use only the inputs listed for its target, so a column that is recorded
later, or that gives the answer away, cannot leak into a prediction. The
lists are allow-lists: a field not named is refused, not trusted.
"""

from __future__ import annotations

import contextvars
import json
import time
from pathlib import Path

from src.aito_client import AitoClient, AitoError

INCOMING = Path(__file__).resolve().parent / "data" / "support_incoming.json"

#: What a ticket carries at intake, before anyone has worked on it.
INTAKE = {"text", "sender", "sender_domain", "contact", "channel", "month", "customer", "product",
          "adoption_band", "repeat_30d"}
#: The linked attributes a prediction may name, per link. An explicit list, like
#: everything else here: `customer.churned` is an outcome recorded on the account
#: and is not on it. (Aito can still see a linked row's columns when `customer` is
#: an input; churn in this fixture is drawn from plan, health and the rest before
#: any ticket, and never from a ticket's outcome, so it carries no target.)
LINKED = {
    "customer": {"industry", "size", "plan", "region", "tenure_band", "seats_band", "onboarding",
                 "health", "nps_band", "csm_motion", "mrr_eur", "primary_product"},
    "product": {"category", "name", "tier"},
    "contact": {"role"},
}

#: target (table, field) -> the inputs it may use. Anything else refuses.
ALLOWED: dict[tuple[str, str], set[str]] = {
    ("support_tickets", "customer"): {"text", "sender_domain"},
    ("support_tickets", "product"): INTAKE - {"product"},
    ("support_tickets", "category"): INTAKE,
    ("support_tickets", "priority"): INTAKE | {"category"},
    ("support_tickets", "resolution"): INTAKE | {"category"},
    ("support_tickets", "kb_article"): INTAKE | {"category"},
    ("support_tickets", "nps_after"): INTAKE | {"category", "priority", "recovery", "first_response"},
    ("support_tickets", "upsell_accepted"): {"adoption_band", "customer", "product", "upsell_offered"},
    ("support_steps", "action"): {"previous_action", "category", "step_no", "ticket.issue", "ticket.category",
                                  "ticket.priority", "ticket.customer", "ticket.text"},
}
#: filters a target must carry: an upsell is only accepted or not when it was offered
REQUIRED: dict[tuple[str, str], dict] = {
    ("support_tickets", "upsell_accepted"): {"upsell_offered": "yes"},
}


class LeakError(ValueError):
    """A prediction asked for an input its target may not use."""


def _allowed(field: str, allowed: set[str]) -> bool:
    if field in allowed:
        return True
    # a linked attribute: its link must be allowed AND the attribute on LINKED's list
    link, _, attr = field.removeprefix("ticket.").rpartition(".")
    via = ("ticket." + link) if field.startswith("ticket.") else link
    return via in allowed and attr in LINKED.get(link, set())


def check_inputs(table: str, target: str, where: dict) -> None:
    key = (table, target)
    if key not in ALLOWED:
        raise LeakError(f"no input list for {table}.{target}: add one before predicting it")
    bad = sorted(f for f in where if not _allowed(f, ALLOWED[key]))
    if bad:
        raise LeakError(f"{table}.{target} may not use {bad} as input (see the inputs-vs-targets table)")
    for f, v in REQUIRED.get(key, {}).items():
        if where.get(f) != v:
            raise LeakError(f"{table}.{target} must be predicted with {f} = {v!r}")


def _p(hit: dict) -> float | None:
    p = hit.get("$p")
    return round(float(p), 3) if isinstance(p, (int, float)) else None


def _ranked(hits: list[dict], where: dict, t0: float) -> dict:
    return {"value": hits[0].get("feature", hits[0].get("$value")) if hits else None,
            "p": _p(hits[0]) if hits else None,
            "alternatives": [{"value": h.get("feature", h.get("$value")), "p": _p(h)} for h in hits[1:]],
            "inputs": sorted(where), "ms": round((time.perf_counter() - t0) * 1000)}


def guarded(aito: AitoClient, table: str, where: dict, target: str, limit: int = 3, why: bool = False) -> dict:
    """_predict through the leak guard; returns the top value, its $p, the runners-up and the latency.
    With `why`, also the top value's drivers from its own $why (field, value, lift)."""
    if any(v is None for v in where.values()):
        raise LeakError(f"{table}.{target}: an input is missing ({sorted(k for k, v in where.items() if v is None)})")
    check_inputs(table, target, where)
    t0 = time.perf_counter()
    hits = aito.predict(table, where, target, limit=limit,
                        select=["$p", "feature", "$why"] if why else ["$p", "feature"]).get("hits") or []
    out = _ranked(hits, where, t0)
    if why and hits:
        from src.app import _why_of, _win_drivers  # the pages' own $why reading; imported late (app imports us)
        out["why"] = _win_drivers(_why_of(hits, out["value"]), k=3)
    return out


def guarded_recommend(aito: AitoClient, table: str, where: dict, field: str, goal: dict, limit: int = 4) -> dict:
    """_recommend through the same guard: the goal is the target, so the context
    AND the recommended field must both be inputs that target may use."""
    (target,) = goal
    check_inputs(table, target, {**where, field: None})
    t0 = time.perf_counter()
    return _ranked(aito.recommend(table, where, field, goal, limit=limit).get("hits") or [], where, t0)


def _soft(fn):
    """One step's Aito call, where an Aito error blanks that step instead of failing the
    ticket: the page shows the other steps, and this one as unanswered. A LeakError is a
    bug in the caller and still raises."""
    def call(*args, **kw):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kw)
        except AitoError as e:
            print(f"[support] {getattr(fn, '__name__', 'step')} degraded: {e} {str(e.body)[:200]}")
            return {"value": None, "p": None, "alternatives": [], "inputs": [], "error": str(e),
                    "ms": round((time.perf_counter() - t0) * 1000)}
    return call


def _p_of(result: dict, value: str) -> float | None:
    """The $p a prediction gave one value, whether it ranked first or not."""
    if result.get("value") == value:
        return result.get("p")
    return next((a["p"] for a in result.get("alternatives", []) if a["value"] == value), None)


def risk_of(value: str, p: float | None, base: float | None) -> dict:
    """A risk reads as a multiple of the usual rate, which a single ticket can't
    prove right or wrong."""
    times = round(p / base, 1) if p is not None and base else None
    return {"risk": {"of": value, "p": p, "base": base, "times": times}, "correct": None, "truth": None}


_BASE: dict[int, dict] = {}


def base_rates(aito: AitoClient) -> dict:
    """The usual detractor and upsell-acceptance rates, from the log, once per client."""
    if id(aito) not in _BASE:
        det = aito.predict("support_tickets", {}, "nps_after", limit=3, select=["$p", "feature"]).get("hits") or []
        ups = aito.predict("support_tickets", {"upsell_offered": "yes"}, "upsell_accepted", limit=2,
                           select=["$p", "feature"]).get("hits") or []
        pick = lambda hits, v: next((round(float(h["$p"]), 3) for h in hits if h.get("feature") == v), None)  # noqa: E731
        _BASE[id(aito)] = {"detractor": pick(det, "detractor"), "upsell_yes": pick(ups, "yes")}
    return _BASE[id(aito)]


def load_incoming(path: Path = INCOMING) -> dict:
    held = json.loads(path.read_text())
    steps: dict[str, list[dict]] = {}
    for s in held["steps"]:
        steps.setdefault(s["ticket"], []).append(s)
    return {"tickets": {t["ticket_id"]: t for t in held["tickets"]},
            "order": [t["ticket_id"] for t in sorted(held["tickets"], key=lambda t: (t["created_at"], t["ticket_id"]))],
            "steps": {k: sorted(v, key=lambda s: s["step_no"]) for k, v in steps.items()}}


#: $p at or above this is served from history; the demo's existing gates (app.py)
AUTO, ASSIST = 0.85, 0.65
DETOURS = {"ask_for_details", "wait_for_customer"}


def _gate(p: float | None) -> str:
    return "auto" if p is not None and p >= AUTO else ("assist" if p is not None and p >= ASSIST else "human")


class _Now:
    """A stand-in executor that runs each call at once: the sequential baseline."""

    def submit(self, fn, *args):
        class _Done:
            def __init__(self, v):
                self.v = v

            def result(self):
                return self.v
        return _Done(fn(*args))


def envelope(aito: AitoClient, ticket: dict, true_steps: list[dict], parallel: bool = True,
             why: bool = False) -> dict:
    """Run every step for one incoming ticket. Truth is attached per step for the
    view to compare with, never passed to a prediction.

    Steps that depend on each other run in order (account -> product -> category ->
    the triage steps -> risk); everything else runs concurrently when `parallel`."""
    from concurrent.futures import ThreadPoolExecutor

    t_start = time.perf_counter()
    intake = {k: ticket[k] for k in ("text", "sender_domain", "channel", "month", "adoption_band", "repeat_30d")}
    entries: dict[str, dict] = {}

    def entry(key, title, op, result, truth=None, note=None):
        if result.get("error"):
            truth, note = None, "Aito could not answer this step just now, so nothing is suggested"
        entries[key] = {"key": key, "title": title, "op": op, **result, "truth": truth,
                        "correct": (result.get("value") == truth) if truth is not None else None, "note": note}
        return entries[key]

    def timed_query(**kw):
        t0 = time.perf_counter()
        hits = aito.query(**kw).get("hits") or []
        return hits, round((time.perf_counter() - t0) * 1000)

    pool = ThreadPoolExecutor(max_workers=8) if parallel else None
    run = pool if pool else _Now()
    g, g_rec = _soft(guarded), _soft(guarded_recommend)

    def sub(fn, *args):
        # each task runs in a copy of this request's context, so its Aito calls are
        # recorded for the side panel like the ones made on this thread
        return run.submit(contextvars.copy_context().run, fn, *args)
    try:
        # 1. who: in a B2B desk the sender is a known contact, so the account is a lookup;
        # only a new address is inferred, from the domain it writes from
        found, ms = timed_query(table="support_contacts", where={"email": ticket["sender"]},
                                select=["contact_id", "name", "role", "customer"], limit=1)
        if found:
            c = found[0]
            entry("customer", "Who is this?", "_query support_contacts",
                  {"value": c["customer"], "p": None, "alternatives": [], "inputs": ["sender"], "ms": ms,
                   "contact": {"name": c.get("name"), "role": c.get("role")}},
                  ticket["customer"], note=f"a known contact: {c.get('name')}, {str(c.get('role', '')).replace('_', ' ')}")
            account, contact = c["customer"], c["contact_id"]
        else:
            who = guarded(aito, "support_tickets", {"sender_domain": ticket["sender_domain"]}, "customer")
            entry("customer", "Who is this?", "_predict customer", who, ticket["customer"],
                  note="a new address: the account is inferred from the domain it writes from")
            account, contact = who["value"], None
        acct = {"customer": account} if account else {}
        known = {**intake, **acct, **({"contact": contact} if contact else {})}

        # needs only the account: start these now, alongside the product -> category chain
        def similar_cases():
            try:
                return timed_query(table="support_tickets", where=acct or None,
                                   select=["ticket_id", "text", "resolution", "nps_after"],
                                   order_by={"$similarity": {"text": ticket["text"]}}, limit=3)
            except AitoError:
                return None, 0
        f_similar = sub(similar_cases)
        f_rec = sub(g_rec, aito, "support_tickets", {**acct, "repeat_30d": ticket["repeat_30d"]},
                           "recovery", {"nps_after": "promoter"})
        f_ups = sub(g, aito, "support_tickets", {"adoption_band": ticket["adoption_band"], **acct,
                                                              "upsell_offered": "yes"}, "upsell_accepted", 2)
        f_base = sub(_soft_base, aito)

        # 2. which product: a shortlist from the text and the account's own products;
        # later steps use its top pick, so a wrong pick shows up downstream too
        prod = g(aito, "support_tickets", known, "product", 3, why)
        e = entry("product", "Which product?", "_predict product  ·  top 3", prod, ticket["product"])
        e["shortlist"] = True
        if ticket["product"] is not None and not prod.get("error"):
            e["correct"] = ticket["product"] in [prod["value"]] + [a["value"] for a in prod["alternatives"]]
        known = {**known, **({"product": prod["value"]} if prod["value"] else {})}

        cat = g(aito, "support_tickets", known, "category", 3, why)
        entry("category", "What is it about?", "_predict category", cat, ticket["category"])
        triaged = {**known, **({"category": cat["value"]} if cat["value"] is not None else {})}

        f_pri = sub(g, aito, "support_tickets", triaged, "priority", 3, why)
        f_res = sub(g, aito, "support_tickets", triaged, "resolution", 3, why)
        f_kb = sub(g, aito, "support_tickets", triaged, "kb_article")
        # the first step reads the ticket's own words through the link: which fix a bug
        # needs (crash or wrong data) is in the text, not in the category
        f_first = sub(g, aito, "support_steps",
                             {"previous_action": "start", "ticket.text": ticket["text"],
                              **({"category": cat["value"]} if cat["value"] is not None else {})}, "action", 3, why)

        pri = f_pri.result()
        entry("priority", "How urgent?", "_predict priority", pri, ticket["priority"])
        # risks, not decisions: a probability against the base rate, shown with what happened,
        # never scored right or wrong on one ticket
        f_risk = sub(g, aito, "support_tickets",
                            {**triaged, **({"priority": pri["value"]} if pri["value"] is not None else {})}, "nps_after", 3)

        res = f_res.result()
        gate = _gate(res["p"])
        entry("resolution", "Does history already decide it?", "_predict resolution  ·  $p gate", res,
              ticket["resolution"])["gate"] = gate
        entry("kb", "Which article helps?", "_predict kb_article", f_kb.result(), ticket["kb_article"])
        similar, ms = f_similar.result()
        entry("similar", "How did this account's similar tickets end?", "_query orderBy $similarity",
              {"value": None, "p": None, "alternatives": [], "inputs": ["text", "customer"], "ms": ms,
               "cases": similar or [], **({"error": "similarity query failed"} if similar is None else {})})
        # scored against the fix's first real action: asking for details or waiting is a detour, not a plan
        real = [s["action"] for s in true_steps if s["action"] not in DETOURS]
        entry("first_step", "Where to start?", "_predict next action", f_first.result(), real[0] if real else None)

        base = f_base.result()
        risk = f_risk.result()
        entry("risk", "Will this customer turn detractor?", "_predict nps_after", risk,
              note="recorded after the ticket; shown, never used as an input").update(
            risk_of("detractor", _p_of(risk, "detractor"), base["detractor"]), happened=ticket["nps_after"])
        entry("recovery", "What protects the relationship?", "_recommend recovery → promoter", f_rec.result(),
              note="the recovery in the log was assigned at random, so its effect is causal")
        ups = f_ups.result()
        entry("upsell", "Is an upsell welcome?", "_predict upsell_accepted", ups).update(
            risk_of("yes", _p_of(ups, "yes"), base["upsell_yes"]),
            happened=ticket["upsell_accepted"] if ticket["upsell_offered"] == "yes" else "no offer made")
    finally:
        if pool:
            # on success every future has been read; on an error, drop the queued calls
            # rather than let them run on, unread, against an Aito that is already failing
            pool.shutdown(wait=False, cancel_futures=True)

    steps = [entries[k] for k in ORDER]
    failed = [s for s in steps if s.get("error")]
    if len(failed) > len(steps) // 2:
        # not one flaky step but Aito failing: say so, rather than show a page of blanks
        raise AitoError(f"Aito failed on {len(failed)} of {len(steps)} steps: {failed[0]['error']}")
    return {"ticket": {k: ticket[k] for k in ("ticket_id", "created_at", "text", "sender_domain", "channel")},
            "steps": steps, "gate": gate, "degraded": [s["key"] for s in steps if s.get("error")], "aito_calls": len(steps), "aito_ms": sum(s["ms"] for s in steps),
            "wall_ms": round((time.perf_counter() - t_start) * 1000)}


def _soft_base(aito: AitoClient) -> dict:
    try:
        return base_rates(aito)
    except AitoError:
        return {"detractor": None, "upsell_yes": None}


#: the order the view shows the steps in
ORDER = ["customer", "product", "category", "priority", "resolution", "kb", "similar", "first_step",
         "risk", "recovery", "upsell"]
