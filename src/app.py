"""FastAPI app for the aito-hello demo template.

Conventions enforced by aito-demo-server (don't drift from these without
updating both the platform and the template in the same PR):

  - GET /health         : cheap liveness, no Aito call
  - GET /api/health     : readiness check, includes Aito connectivity
  - GET /api/schema     : pass-through to Aito's /schema (linked from AitoPanel)
  - GET /api/<...>      : your routes
  - app.mount("/", StaticFiles(directory="frontend/out", html=True))
                         : MUST be the last route registered. Serves the
                           Next.js static export from the same uvicorn process.

Replace the /api/example handler with your own routes. /health, /api/health,
and /api/schema can stay verbatim across demos.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from src.aito_client import AitoClient, AitoError
from src.config import load_config

# Each support intent fills exactly one structured parameter (or none). The
# predictive layer reads both straight from the ticket — no separate tool calls.
INTENT_PARAM = {
    "cancel_service": "target_service",
    "refund": "target_service",
    "check_outage": "location",
    "find_shop": "location",
    "repair_help": "kb_article",
    "check_balance": None,
}

config = load_config()
aito = AitoClient(config)

app = FastAPI(
    title="Aito Agent demo",
    description="Replace with your demo's name & description.",
    version="0.1.0",
)


# ── Middleware: surface Aito latency in response headers ─────────────
#
# The LatencyBadge in the frontend reads X-Aito-Ms / X-Aito-Calls /
# X-Aito-Ops set on every /api/* response. Reset the client's
# last_call before the route runs; pick it up after.

@app.middleware("http")
async def aito_latency_headers(request: Request, call_next):
    aito.last_call = None
    response: Response = await call_next(request)
    if aito.last_call:
        call = aito.last_call
        response.headers["X-Aito-Ms"] = f"{call.ms:.1f}"
        response.headers["X-Aito-Calls"] = "1"
        response.headers["X-Aito-Ops"] = f"{call.op}:{call.ms:.1f}"
    return response


# ── Rate limit: the live LLM endpoints are public and paid per call ──
#
# Aito predictions are cheap and stay unthrottled; the gpt-5-mini routes get a
# light per-IP sliding-window cap as abuse insurance (nginx forwards the real
# client IP in X-Forwarded-For). In-memory is fine — one uvicorn process, and a
# demo doesn't need a shared store.
_LLM_PATHS = {"/api/resolve-llm", "/api/sales-agent/chat", "/api/company-agent/chat"}
_RL_MAX = 20          # requests
_RL_WINDOW = 60.0     # seconds
_rl_hits: dict[str, list[float]] = {}


@app.middleware("http")
async def rate_limit_llm(request: Request, call_next):
    if request.url.path in _LLM_PATHS:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "anon")
        now = time.monotonic()
        recent = [t for t in _rl_hits.get(ip, []) if now - t < _RL_WINDOW]
        if len(recent) >= _RL_MAX:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "Too many AI requests from your network — give it a few seconds."},
                status_code=429,
            )
        recent.append(now)
        _rl_hits[ip] = recent
        if len(_rl_hits) > 5000:  # bound memory: drop anyone with no live hits
            for k in [k for k, v in _rl_hits.items() if not any(now - t < _RL_WINDOW for t in v)]:
                _rl_hits.pop(k, None)
    return await call_next(request)


# ── Health ────────────────────────────────────────────────────────

@app.get("/health")
def liveness():
    """Cheap liveness probe — does not touch Aito.

    The platform's nginx routes <demo>.aito.ai/health to this endpoint
    so external monitoring can target a specific demo. Keep it cheap.
    """
    return {"ok": True}


@app.get("/api/health")
def readiness():
    """Aito-connectivity readiness probe."""
    connected = aito.check_connectivity()
    return {
        "status": "ok" if connected else "degraded",
        "aito_url": aito.base_url,
        "aito_connected": connected,
    }


@app.get("/api/schema")
def schema():
    """Pass-through to Aito's /schema. The AitoPanel "view live schema" link
    targets this endpoint, so users can verify what's actually in the DB."""
    try:
        return aito.get_schema()
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Resolution route — predict the whole resolution from the ticket ─────

# Tokens to drop when explaining a text match — they carry no signal a user
# would recognise as "why".
_STOP = {
    "a", "an", "the", "is", "are", "was", "there", "in", "on", "of", "to", "for",
    "and", "or", "my", "i", "you", "it", "this", "that", "with", "at", "be", "im",
    "please", "hi", "hello", "hey", "we", "me", "do", "does", "can", "could", "would",
}
import re as _re


def _why_props(prop: dict):
    """Yield (field, value) pairs from a _why proposition (handles $and nesting)."""
    if not isinstance(prop, dict):
        return
    if "$and" in prop:
        for sub in prop["$and"]:
            yield from _why_props(sub)
        return
    for field, cond in prop.items():
        if isinstance(cond, dict):
            for _op, val in cond.items():
                yield field, val


def _flatten_why(node, out: list):
    """Collect leaf factors (baseP / relatedPropositionLift) from the product tree."""
    if not isinstance(node, dict):
        return
    if node.get("type") == "product":
        for f in node.get("factors", []):
            _flatten_why(f, out)
    else:
        out.append(node)


def _mark_text(text: str, stems: set[str]) -> str:
    """Wrap ticket words that match a content stem in <mark> (Aito stems tokens,
    so we match by prefix)."""
    def repl(m: _re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if any(len(s) >= 3 and lw.startswith(s) for s in stems):
            return f"<mark>{w}</mark>"
        return w
    return _re.sub(r"[A-Za-zÀ-ÿ]+", repl, text)


def _transform_why(raw: dict, ticket_text: str, predicted: str, max_patterns: int = 1) -> list[dict]:
    """Aito `$why` → the frontend WhyFactor[] shape (base + the single strongest
    pattern). We show one pattern, not several: Aito's per-token lifts are
    overlapping conjunctions, so multiplying a handful of them overshoots wildly
    — base × the strongest lift ≈ the calibrated result is the honest summary."""
    leaves: list = []
    _flatten_why(raw, leaves)
    factors: list[dict] = []
    for leaf in leaves:
        if leaf.get("type") == "baseP":
            factors.append({"type": "base", "base_p": float(leaf.get("value", 0)), "target_value": predicted})

    patterns = []
    for leaf in leaves:
        if leaf.get("type") != "relatedPropositionLift":
            continue
        lift = float(leaf.get("value", 1.0))
        text_stems = {v for f, v in _why_props(leaf.get("proposition", {})) if f == "text"}
        content = {s for s in text_stems if len(s) >= 3 and s not in _STOP}
        others = [(f, v) for f, v in _why_props(leaf.get("proposition", {})) if f != "text"]
        if not content and not others:
            continue
        pf: dict = {"type": "pattern", "lift": lift, "propositions": [], "highlights": []}
        if content:
            pf["highlights"].append({"field": "text", "html": _mark_text(ticket_text, content)})
        for f, v in others:
            pf["propositions"].append({"field": f, "value": str(v)})
        patterns.append((abs(lift - 1.0), pf))

    patterns.sort(key=lambda x: x[0], reverse=True)
    factors.extend(pf for _, pf in patterns[:max_patterns])
    return factors


def _top_and_alts(resp: dict, k: int = 3):
    hits = resp.get("hits") or []
    if not hits or "$p" not in hits[0]:
        raise AitoError(f"unexpected _predict shape: {str(resp)[:200]}")
    alts = [
        {"value": h.get("feature"), "display": h.get("feature"), "confidence": float(h["$p"])}
        for h in hits[:k] if h.get("feature") is not None
    ]
    return hits[0].get("feature"), float(hits[0]["$p"]), alts


@app.get("/api/resolve")
def resolve(text: str, sender: str = ""):
    """Resolve a support ticket via Aito `_predict`: predict the intent, then the
    one structured parameter that intent needs — both from `{text, sender_domain}`,
    no customer/subscription/invoice lookups. Returns the resolution + calibrated
    confidence + measured Aito latency."""
    where: dict = {"text": text}
    if sender:
        where["sender_domain"] = sender
    try:
        t0 = time.perf_counter()
        intent_resp = aito.predict("resolutions", where, "intent", limit=3, select=["$p", "feature", "$why"])
        intent, intent_p, intent_alts = _top_and_alts(intent_resp)
        raw_why = (intent_resp.get("hits") or [{}])[0].get("$why")
        why = _transform_why(raw_why, text, intent) if raw_why else []
        param_field = INTENT_PARAM.get(intent)
        param = param_p = None
        param_alts: list = []
        if param_field:
            param, param_p, param_alts = _top_and_alts(aito.predict("resolutions", where, param_field, limit=3))
        aito_ms = (time.perf_counter() - t0) * 1000
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "text": text,
        "sender": sender,
        "intent": intent,
        "intent_p": intent_p,
        "intent_alts": intent_alts,
        "why": why,
        "param_field": param_field,
        "param": param,
        "param_p": param_p,
        "param_alts": param_alts,
        "aito_ms": round(aito_ms, 1),
    }


# ── Live LLM agent — the side-by-side response-rate comparison ─────

@app.get("/api/resolve-llm")
def resolve_llm(text: str, sender: str = ""):
    """Resolve the SAME ticket with a live gpt-5-mini call, so the UI can show the
    real latency/cost next to Aito's instant prediction. One structured call —
    the generous baseline (a real tool-calling agent would chain several)."""
    from src.llm_agent import cost_usd, get_agent

    try:
        agent = get_agent()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM agent unavailable: {e}")
    try:
        r = agent.resolve(text)
    except Exception as e:  # noqa: BLE001 — surface any LLM failure as 502
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")
    param_field = INTENT_PARAM.get(r.intent)
    param = r.fields.get(param_field) if param_field else None
    return {
        "text": text,
        "intent": r.intent,
        "param_field": param_field,
        "param": param,
        "model": r.model,
        "latency_ms": round(r.latency_ms, 1),
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "tokens": r.input_tokens + r.output_tokens,
        "cost_usd": round(cost_usd(r.input_tokens, r.output_tokens), 6),
    }


# ── Human handoff — the agent knows what it doesn't know ──────────

_HANDOFF_QUEUE = [
    "Is there a network outage? Nothing works in Helsinki.",
    "My screen is cracked, the glass is shattered.",
    "What's my current account balance?",
    "Where's your nearest shop in Tampere?",
    "My battery dies within an hour now.",
    "Nothing has worked properly since last week and I want real answers.",
    "I am not sure, can someone just call me back",
    "I have a few different problems with my account and nobody is helping me",
    "Please cancel my home internet, I'm moving abroad.",
    "Hi — please refund the €45 charge on my roaming pack.",
]
_TEAM = {
    "refund": "Billing", "check_balance": "Billing", "check_outage": "Network Ops",
    "repair_help": "Tech Support", "cancel_service": "Retention", "find_shop": "Sales",
}
_SENSITIVE = {"refund", "cancel_service"}
_AUTO_GATE, _ASSIST_GATE = 0.85, 0.65


@app.get("/api/handoff")
def handoff():
    """Triage an incoming queue by Aito's calibrated confidence: auto-resolve the
    sure ones, assist the medium, and hand the rest to a human — with Aito's
    tentative read attached, so the human starts informed, not from scratch.
    Sensitive actions (money/state-change) always go to a human to verify."""
    rows = []
    try:
        for text in _HANDOFF_QUEUE:
            intent, p, alts = _top_and_alts(aito.predict("resolutions", {"text": text}, "intent", limit=3, select=["$p", "feature"]))
            if p < _ASSIST_GATE:  # unsure first — Aito won't guess, regardless of intent
                band, reason = "handoff", f"low confidence ({p*100:.0f}%) — Aito won't guess on this"
            elif intent in _SENSITIVE:  # confident, but money/state-change → verify with a human
                band, reason = "handoff", f"sensitive action ({intent.replace('_', ' ')}) — needs human verification"
            elif p >= _AUTO_GATE:
                band, reason = "auto", None
            else:
                band, reason = "assist", None
            rows.append({"text": text, "intent": intent, "p": p, "alts": alts,
                         "band": band, "reason": reason, "team": _TEAM.get(intent, "Support")})
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    counts = {"auto": 0, "assist": 0, "handoff": 0}
    for r in rows:
        counts[r["band"]] += 1
    return {"total": len(rows), "counts": counts, "handoff": [r for r in rows if r["band"] == "handoff"]}


# ── Cooperation: Aito short-lists, the LLM decides ────────────────

import json as _json

_CATALOG = _json.loads((Path(__file__).resolve().parent / "tools_catalog.json").read_text())
_CATALOG_BY_NAME = {t["name"]: t for t in _CATALOG}


@app.get("/api/route")
def route(text: str):
    """Augmentation demo (short-listing). Aito `_predict` shortlists the few tools
    that history says are relevant; the SAME LLM then picks — once over the whole
    catalog (alone) and once over Aito's shortlist (cooperation) — so you can see
    that Aito makes the model faster/cheaper/grounded rather than replacing it."""
    from src.llm_agent import cost_usd, get_agent

    where = {"text": text}
    try:
        # tool-routing history lives in `tool_calls` (the company demo owns `tickets`)
        sl = aito.predict("tool_calls", where, "tool", limit=5, select=["$p", "feature"])
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    hits = sl.get("hits") or []
    shortlist = [{"tool": h.get("feature"), "p": float(h["$p"])} for h in hits if h.get("feature")]
    aito_ms = aito.last_call.ms if aito.last_call else None

    try:
        agent = get_agent()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM agent unavailable: {e}")

    def _llm(tools: list[dict]) -> dict:
        r = agent.pick_tool(text, tools)
        return {"tool": r.tool, "latency_ms": round(r.latency_ms, 1),
                "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                "tokens": r.input_tokens + r.output_tokens,
                "cost_usd": round(cost_usd(r.input_tokens, r.output_tokens), 6),
                "n_tools": len(tools)}

    shortlist_tools = [_CATALOG_BY_NAME[s["tool"]] for s in shortlist if s["tool"] in _CATALOG_BY_NAME]
    try:
        full = _llm(_CATALOG)
        coop = _llm(shortlist_tools) if shortlist_tools else None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    return {
        "text": text,
        "catalog_size": len(_CATALOG),
        "shortlist": shortlist,
        "aito_ms": round(aito_ms, 1) if aito_ms is not None else None,
        "aito_top_p": shortlist[0]["p"] if shortlist else None,
        "llm_full": full,
        "llm_coop": coop,
        "model": agent.model,
    }


# ── Sales assistant — the firm's intuition for a new opportunity ──

_DEAL_VALUE = {"S": 35000, "M": 100000, "L": 275000, "XL": 600000}
_DAY_RATE = 1100


def _win_drivers(raw_why, k: int = 3):
    leaves: list = []
    _flatten_why(raw_why, leaves)
    out = []
    for leaf in leaves:
        if leaf.get("type") == "relatedPropositionLift":
            lift = float(leaf.get("value", 1.0))
            for f, v in _why_props(leaf.get("proposition", {})):
                if f != "brief":
                    out.append({"field": f, "value": str(v), "lift": round(lift, 2)})
    out.sort(key=lambda d: abs(d["lift"] - 1), reverse=True)
    return out[:k]


@app.get("/api/opportunity")
def opportunity(industry: str = "SaaS", client_size: str = "Mid-market", service_line: str = "Data Platform",
                deal_size_band: str = "L", region: str = "Helsinki", lead_source: str = "Inbound",
                complexity: str = "Medium", team_seniority: str = "balanced", relationship: str = "New logo",
                competitive: str = "Competitive", target_role: str = "Head of Data"):
    """One deal sheet from the firm's history: win-likelihood (+ drivers), an
    effort/cost estimate, reference projects to cite, and the outreach most likely
    to land — gated for auto-send by its predicted meeting probability."""
    eng_where = {"client_industry": industry, "client_size": client_size, "service_line": service_line,
                 "deal_size_band": deal_size_band, "complexity": complexity, "team_seniority": team_seniority,
                 "lead_source": lead_source, "relationship": relationship, "competitive": competitive, "region": region}
    try:
        wr = aito.predict("engagements", eng_where, "outcome", limit=2, select=["$p", "feature", "$why"])
        whits = wr.get("hits") or []
        won_p = next((float(h["$p"]) for h in whits if h.get("feature") == "won"), 0.0)
        drivers = _win_drivers((whits[0] if whits else {}).get("$why"))

        er = aito.estimate("engagements", {"service_line": service_line, "deal_size_band": deal_size_band,
                                            "complexity": complexity, "team_seniority": team_seniority,
                                            "client_industry": industry}, "effort_days")
        effort = round(float(er.get("estimate", 0)))

        refs = (aito.query("engagements", where={"client_industry": industry, "service_line": service_line, "outcome": "won"},
                           select=["brief", "effort_days", "deal_size_band", "region"], limit=3).get("hits") or [])

        out_where = {"target_industry": industry, "target_role": target_role}
        ch = (aito.recommend("outreach", out_where, "channel", {"meeting": "yes"}, limit=4).get("hits") or [])
        ang = (aito.recommend("outreach", out_where, "angle", {"meeting": "yes"}, limit=5).get("hits") or [])
        top_ch = ch[0]["feature"] if ch else "Warm intro"
        top_ang = ang[0]["feature"] if ang else "Case study"
        mr = aito.predict("outreach", {"target_industry": industry, "target_role": target_role,
                                        "channel": top_ch, "angle": top_ang, "personalization": "High",
                                        "subject_style": "Name-drop", "send_day": "Tue"}, "meeting", limit=2)
        meeting_p = next((float(h["$p"]) for h in (mr.get("hits") or []) if h.get("feature") == "yes"), 0.0)
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))

    value = _DEAL_VALUE.get(deal_size_band, 100000)
    cost = effort * _DAY_RATE
    margin = value - cost
    return {
        "profile": {"industry": industry, "client_size": client_size, "service_line": service_line,
                    "deal_size_band": deal_size_band, "region": region, "lead_source": lead_source,
                    "complexity": complexity, "team_seniority": team_seniority, "relationship": relationship,
                    "competitive": competitive, "target_role": target_role},
        "win": {"p": won_p, "drivers": drivers},
        "effort_days": effort,
        "references": [{"brief": r.get("brief"), "effort_days": r.get("effort_days"),
                        "deal_size_band": r.get("deal_size_band"), "region": r.get("region")} for r in refs],
        "outreach": {
            "channels": [{"v": h["feature"], "p": float(h["$p"])} for h in ch],
            "angles": [{"v": h["feature"], "p": float(h["$p"])} for h in ang],
            "recommended": {"channel": top_ch, "angle": top_ang, "personalization": "High"},
            "meeting_p": meeting_p,
            "auto_send": meeting_p >= 0.32,
        },
        "business_case": {"value_eur": value, "day_rate": _DAY_RATE, "cost_eur": cost,
                          "margin_eur": margin, "margin_pct": round(margin / value * 100) if value else 0},
    }


# ── Sales agent — Aito ops as tools in an LLM agent's toolbox ──────
#
# The chat agent (src/sales_agent.py) does the reasoning; these are the tool
# *implementations* it calls. Four are Aito ops over the firm's history; the
# fifth (propose_send_email) is a plain action that only ever queues a DRAFT —
# it never sends, honouring the "no auto-fired state changes" rule.

def _eng_where(args: dict) -> dict:
    """Map tool args → engagements columns, dropping anything the model omitted."""
    m = {"industry": "client_industry", "client_size": "client_size", "service_line": "service_line",
         "deal_size_band": "deal_size_band", "lead_source": "lead_source", "relationship": "relationship",
         "competitive": "competitive", "complexity": "complexity", "team_seniority": "team_seniority"}
    return {col: args[k] for k, col in m.items() if args.get(k)}


def _tool_win_odds(args: dict) -> dict:
    where = _eng_where(args)
    if not where:
        return {"error": "need at least one field (industry, service_line, lead_source, …) to read win odds"}
    r = aito.predict("engagements", where, "outcome", limit=2, select=["$p", "feature", "$why"])
    hits = r.get("hits") or []
    won_p = next((float(h["$p"]) for h in hits if h.get("feature") == "won"), 0.0)
    return {
        "win_probability": round(won_p, 2),
        "drivers": _win_drivers((hits[0] if hits else {}).get("$why")),
        "based_on": "Northlight's won/lost engagements with these attributes",
    }


def _tool_estimate_effort(args: dict) -> dict:
    where = {k: v for k, v in {
        "service_line": args.get("service_line"), "deal_size_band": args.get("deal_size_band"),
        "complexity": args.get("complexity"), "team_seniority": args.get("team_seniority"),
        "client_industry": args.get("industry"),
    }.items() if v}
    if not where:
        return {"error": "need service_line / deal_size_band / complexity to estimate effort"}
    est = aito.estimate("engagements", where, "effort_days").get("estimate")
    if est is None:
        return {"error": "no estimate available for that context"}
    return {"effort_days": round(float(est)), "based_on": "similar past engagements"}


def _tool_find_references(args: dict) -> dict:
    where = {"outcome": "won"}
    if args.get("industry"):
        where["client_industry"] = args["industry"]
    if args.get("service_line"):
        where["service_line"] = args["service_line"]
    refs = (aito.query("engagements", where=where,
                       select=["brief", "effort_days", "deal_size_band", "region"], limit=3).get("hits") or [])
    return {"references": [{"brief": r.get("brief"), "effort_days": r.get("effort_days"),
                            "deal_size_band": r.get("deal_size_band"), "region": r.get("region")} for r in refs],
            "count": len(refs)}


def _meeting_p(where: dict) -> float:
    mr = aito.predict("outreach", where, "meeting", limit=2)
    return next((float(h["$p"]) for h in (mr.get("hits") or []) if h.get("feature") == "yes"), 0.0)


def _tool_recommend_outreach(args: dict) -> dict:
    where = {k: v for k, v in {"target_industry": args.get("industry"),
                               "target_role": args.get("target_role")}.items() if v}
    if not where:
        return {"error": "need target industry or role to recommend outreach"}
    # _recommend = optimize, not describe: rank the actions that maximise meeting=yes
    ch = (aito.recommend("outreach", where, "channel", {"meeting": "yes"}, limit=3).get("hits") or [])
    ang = (aito.recommend("outreach", where, "angle", {"meeting": "yes"}, limit=3).get("hits") or [])
    top_ch = ch[0]["feature"] if ch else "Warm intro"
    top_ang = ang[0]["feature"] if ang else "Case study"
    # recommended approach vs the baseline = expected meeting rate for this target
    # WITHOUT optimising the approach (the prior). The ratio is the live "outcome lift".
    rec_p = _meeting_p({**where, "channel": top_ch, "angle": top_ang,
                        "personalization": "High", "subject_style": "Name-drop", "send_day": "Tue"})
    base_p = _meeting_p(where)
    lift = round(rec_p / base_p, 1) if base_p > 0 else None
    return {"channel": top_ch, "angle": top_ang, "personalization": "High",
            "meeting_probability": round(rec_p, 2),
            "baseline_meeting_probability": round(base_p, 2),
            "outcome_lift": lift,  # e.g. 3.7 → 3.7× more meetings than the unoptimised default
            "clears_auto_send_gate": rec_p >= 0.32}


def _tool_propose_send_email(args: dict) -> dict:
    # Never sends. Always returns a draft-queued status for human approval.
    return {"status": "draft_queued_for_approval", "sent": False,
            "to": args.get("to", "(unspecified)"), "subject": args.get("subject", ""),
            "note": "Draft saved for the rep to review and send — nothing was sent automatically."}


_SALES_TOOL_IMPLS = {
    "win_odds": _tool_win_odds,
    "estimate_effort": _tool_estimate_effort,
    "find_references": _tool_find_references,
    "recommend_outreach": _tool_recommend_outreach,
    "propose_send_email": _tool_propose_send_email,
}


# ── Company AI agent — a 360° copilot that optimises KPIs ──────────
#
# A single `customers` master is linked (Aito link) to deals/tickets/usage/
# invoices/feedback + a `products` catalog, so predictions on a child table can
# use the linked customer's attributes (where {"customer.size": …}) and one
# customer joins across every domain. Each KPI is a _predict target with an
# actionable lever for _recommend. launch_play only ever drafts.

# kpi → {table, target, "good" value, "bad" value (for root-cause _relate), the
# lever to _recommend, the fields to relate as causes, labels}
_KPIS = {
    "conversion": {"label": "Conversion", "table": "deals", "target": "converted", "good": "yes", "bad": "no",
                   "bad_label": "lost deals", "good_label": "won deals",
                   "lever": "nurture_track", "lever_label": "nurture track",
                   "causes": ["source", "trial_length", "customer.size", "customer.plan", "customer.health"]},
    "churn": {"label": "Churn", "table": "customers", "target": "churned", "good": "no", "report": "yes", "bad": "yes",
              "bad_label": "churned customers", "good_label": "retained customers",
              "lever": "csm_motion", "lever_label": "CSM motion",
              "causes": ["health", "onboarding", "nps_band", "tenure_band", "seats_band"]},
    "nps": {"label": "NPS", "table": "feedback", "target": "score_band", "good": "promoter", "report": "detractor",
            "bad": "detractor", "bad_label": "detractors", "good_label": "promoters",
            "lever": "theme", "lever_label": "theme to fix",
            "causes": ["channel", "survey_type", "customer.health", "customer.onboarding", "customer.plan"]},
    "csat": {"label": "CSAT", "table": "tickets", "target": "csat_band", "good": "good", "bad": "bad",
             "bad_label": "bad ratings", "good_label": "good ratings",
             "lever": "channel", "lever_label": "support channel",
             "causes": ["category", "priority", "first_response", "customer.size", "customer.plan"]},
    "adoption": {"label": "Adoption", "table": "usage", "target": "active", "good": "yes", "bad": "no",
                 "bad_label": "inactive seats", "good_label": "active seats",
                 "lever": "onboarding_push", "lever_label": "onboarding push",
                 "causes": ["adoption_band", "customer.onboarding", "customer.health", "customer.plan"]},
    "ontime": {"label": "On-time revenue", "table": "invoices", "target": "status", "good": "paid", "report": "overdue",
               "bad": "overdue", "bad_label": "overdue invoices", "good_label": "paid invoices",
               "lever": "term", "lever_label": "billing term",
               "causes": ["amount_band", "customer.plan", "customer.size", "customer.industry", "customer.health"]},
}


def _seg_where(table: str, args: dict) -> dict:
    """Customer segment {industry,size,plan} → where, dotted through the link for
    child tables (customer.size) and direct on the customers master."""
    prefix = "" if table == "customers" else "customer."
    return {f"{prefix}{k}": args[k] for k in ("industry", "size", "plan") if args.get(k)}


def _p_of(hits: list, feature: str) -> float:
    return next((float(h["$p"]) for h in hits if h.get("feature") == feature), 0.0)


# structural / identity fields that are never useful "causes"
_NON_CAUSE = {"mrr_eur", "name", "primary_product", "product", "duration_weeks", "brief", "customer", "region"}


def _is_cause_field(field: str, exclude: set[str]) -> bool:
    return field not in exclude and field not in _NON_CAUSE and not field.endswith("_id") and not field.endswith("Id")


def _relate_drivers(table: str, target_field: str, bad: str, seg_props: list[dict],
                    exclude: set[str], candidates: list[str], k: int = 3) -> list[dict]:
    """Root causes of the BAD outcome. With a segment, _relate `$on` scopes to it and
    returns each driver's WITHIN-SEGMENT outcome RATE (e.g. Red-health customers churn
    at 44% vs 28% otherwise → mode 'rate'). With no segment, relate globally and return
    the SHARE of the bad outcome carrying each value (mode 'share'). Strongest factors
    by |lift-1| (drivers >1 and protective <1), one per field."""
    target = {target_field: bad}
    scored: list[dict] = []
    try:
        if seg_props:  # scoped: $on → condition holds the driver, ps gives RATES
            on = seg_props[0] if len(seg_props) == 1 else {"$and": seg_props}
            hits = aito.relate_on(table, target, on).get("hits") or []
            mode, prop_key = "rate", "condition"
        else:          # global: relate the bad outcome to candidate fields → SHARES
            hits = aito.relate(table, target, [f for f in candidates if f not in exclude]).get("hits") or []
            mode, prop_key = "share", "related"
    except AitoError:
        return []
    for h in hits:
        lift = float(h.get("lift", 1.0))
        ps = h.get("ps") or {}
        for f, v in _why_props(h.get(prop_key) or {}):
            field = f.replace("customer.", "")
            if not _is_cause_field(field, exclude):
                continue
            scored.append({
                "field": field, "value": str(v), "lift": round(lift, 2), "mode": mode,
                "p_with": round(float(ps.get("pOnCondition", 0.0)), 3),
                "p_without": round(float(ps.get("pOnNotCondition", 0.0)), 3),
                "_score": abs(lift - 1),
            })
    scored.sort(key=lambda d: -d["_score"])
    out, seen = [], set()
    for d in scored:
        if abs(d["lift"] - 1) < 0.10 or d["field"] in seen:
            continue
        seen.add(d["field"])
        out.append({key: d[key] for key in ("field", "value", "lift", "mode", "p_with", "p_without")})
        if len(out) >= k:
            break
    return out


def _kpi_why(why_node) -> dict:
    """Explain the KPI RATE itself from the prediction's $why: base rate × the
    segment attributes' lifts (e.g. base 23% × Free ×1.5 = 35%)."""
    leaves: list = []
    _flatten_why(why_node, leaves)
    base = None
    factors: list[dict] = []
    for leaf in leaves:
        if leaf.get("type") == "baseP" and base is None:
            base = round(float(leaf.get("value", 0)), 3)
        elif leaf.get("type") == "relatedPropositionLift":
            lift = round(float(leaf.get("value", 1)), 2)
            for f, v in _why_props(leaf.get("proposition", {})):
                if f != "brief":
                    factors.append({"field": f.replace("customer.", ""), "value": str(v), "lift": lift})
    return {"base": base, "factors": factors[:4]}


def _tool_kpi_snapshot(args: dict) -> dict:
    """The 360 card: the headline rate for every KPI in this segment."""
    out = {}
    for kpi, cfg in _KPIS.items():
        where = _seg_where(cfg["table"], args)
        hits = aito.predict(cfg["table"], where, cfg["target"], limit=4, select=["$p", "feature"]).get("hits") or []
        shown = cfg.get("report", cfg["good"])
        out[kpi] = {"metric": cfg["label"], "value": shown, "p": round(_p_of(hits, shown), 2)}
    return {"segment": {k: args[k] for k in ("industry", "size", "plan") if args.get(k)} or "all customers",
            "kpis": out}


def _tool_optimize_kpi(args: dict) -> dict:
    kpi = args.get("kpi")
    cfg = _KPIS.get(kpi)
    if not cfg:
        return {"error": f"unknown kpi '{kpi}'"}
    table, target, good, bad = cfg["table"], cfg["target"], cfg["good"], cfg["bad"]
    where = _seg_where(table, args)
    # headline framed in the KPI's natural direction: churn/detractor/overdue are
    # "lower is better", so we report (and explain) that falling rate.
    report = cfg.get("report")
    lower_better = bool(report) and report != good
    focus = report if lower_better else good   # the outcome whose rate we report/explain
    hits = aito.predict(table, where, target, limit=4, select=["$p", "feature", "$why"]).get("hits") or []
    current = round(_p_of(hits, good), 2)
    # KPI RATE $why: explain the rate itself from the segment attributes' lifts
    # (base 23% × Free ×1.5 = 35%) — the "?" next to the headline number.
    focus_hit = next((h for h in hits if h.get("feature") == focus), None)
    kpi_why = _kpi_why((focus_hit or {}).get("$why"))
    # CAUSES (diagnosis): _relate the BAD outcome to all fields, scoped to the segment
    # via $on — within-segment driver RATES; two-sided (drivers >1, protective <1).
    seg_props = [{f: v} for f, v in where.items()]
    exclude = {target, cfg["lever"], "industry", "size", "plan"}
    causes = _relate_drivers(table, target, bad, seg_props, exclude, cfg["causes"], k=3)
    # LEVERS (prescription): _recommend ranks the lever values toward the goal (it
    # conditions properly, unlike relating the good outcome). Each is shown as a lift
    # = P(good | this lever) / the segment's current good-rate.
    rec = (aito.recommend(table, where, cfg["lever"], {target: good}, limit=3).get("hits") or [])
    lever_items = []
    for h in rec:
        p = round(float(h["$p"]), 2)
        lever_items.append({"value": h["feature"], "p": p,
                            "lift": round(p / current, 2) if current > 0 else 1.0})
    best = lever_items[0]["value"] if lever_items else None
    ph: list = []
    projected = current
    if best is not None:
        ph = aito.predict(table, {**where, cfg["lever"]: best}, target, limit=4, select=["$p", "feature"]).get("hits") or []
        projected = round(_p_of(ph, good), 2)
    now = round(_p_of(hits, report), 2) if lower_better else current
    then = (round(_p_of(ph, report), 2) if (lower_better and best is not None) else (now if lower_better else projected))
    return {
        "kpi": cfg["label"], "goal": f"{target}={good}",
        "headline": {"metric": cfg["label"], "now": now, "then": then, "lower_is_better": lower_better},
        "current": current,
        "bad_label": cfg["bad_label"], "good_label": cfg["good_label"],
        "kpi_why": kpi_why,   # base × segment-attribute lifts = the rate
        "causes": causes, "drivers": causes,   # within-segment drivers ($on _relate)
        "levers": {"lever": cfg["lever_label"], "items": lever_items},  # condition = the good outcome
        "recommended_play": {"lever": cfg["lever_label"], "change_to": best},
        "projected": projected,
        "lift_pp": round(abs(then - now) * 100),
        "note": "Aito has no training step — log this play's outcome and it sharpens the next prediction.",
    }


_360_SELECT = {
    "deals": ["product", "source", "nurture_track", "converted"],
    "tickets": ["product", "category", "priority", "csat_band", "resolved"],
    "usage": ["product", "adoption_band", "active"],
    "invoices": ["term", "amount_band", "status"],
    "feedback": ["survey_type", "theme", "score_band"],
}


def _tool_customer_360(args: dict) -> dict:
    cid = args.get("customer_id")
    if not cid:
        return {"error": "customer_id required (use find_examples with domain='customers')"}
    cust = (aito.query("customers", where={"customer_id": cid}, limit=1).get("hits") or [])
    if not cust:
        return {"error": f"no customer {cid}"}
    profile = cust[0]
    domains = {}
    for tbl, sel in _360_SELECT.items():
        r = aito.query(tbl, where={"customer": cid}, select=sel, limit=4)
        domains[tbl] = {"count": r.get("total", 0), "examples": r.get("hits") or []}
    return {"profile": {k: profile.get(k) for k in
                        ("customer_id", "name", "industry", "size", "plan", "health", "nps_band",
                         "csm_motion", "mrr_eur", "churned")},
            "domains": domains}


def _tool_find_examples(args: dict) -> dict:
    domain = args.get("domain")
    if domain not in _KPIS and domain not in ("customers",) and domain not in _360_SELECT:
        return {"error": f"unknown domain '{domain}'"}
    where = _seg_where(domain, args)
    if domain == "customers" and args.get("churned"):
        where["churned"] = args["churned"]
    sel = (["customer_id", "name", "industry", "size", "plan", "health", "churned"] if domain == "customers"
           else ["customer", *_360_SELECT.get(domain, [])])
    rows = (aito.query(domain, where=where or None, select=sel, limit=6).get("hits") or [])
    return {"domain": domain, "count": len(rows), "rows": rows}


def _tool_estimate_mrr(args: dict) -> dict:
    where = {k: v for k, v in {"plan": args.get("plan"), "size": args.get("size"),
                               "seats_band": args.get("seats_band"), "industry": args.get("industry")}.items() if v}
    if not where:
        return {"error": "need plan / size / seats to estimate MRR"}
    est = aito.estimate("customers", where, "mrr_eur").get("estimate")
    if est is None:
        return {"error": "no estimate for that segment"}
    return {"mrr_eur_estimate": round(float(est)), "based_on": "similar customers"}


def _tool_launch_play(args: dict) -> dict:
    return {"status": "draft_created_for_approval", "acted": False,
            "kpi": args.get("kpi"), "segment": args.get("segment", "(unspecified)"),
            "play": args.get("play", ""), "expected_impact": args.get("expected_impact", ""),
            "note": "Play drafted for a human to approve — nothing was run automatically."}


_COMPANY_TOOL_IMPLS = {
    "kpi_snapshot": _tool_kpi_snapshot,
    "optimize_kpi": _tool_optimize_kpi,
    "customer_360": _tool_customer_360,
    "find_examples": _tool_find_examples,
    "estimate_mrr": _tool_estimate_mrr,
    "launch_play": _tool_launch_play,
}


async def _agent_chat(request: Request, run_turn, impls: dict, all_names: list[str], aito_names: list[str]):
    """Shared one-turn chat handler for the conversational agents. Body:
        {messages: [{role, content}...], aito_enabled?: bool, enabled_tools?: [name]}
    Leaving the Aito tools out (aito_enabled=false) is the augment-vs-replace toggle."""
    body = await request.json()
    messages = body.get("messages") or []
    if not messages:
        raise HTTPException(status_code=400, detail="messages required")
    if body.get("enabled_tools") is not None:
        enabled = [n for n in body["enabled_tools"] if n in all_names]
    else:
        enabled = all_names if body.get("aito_enabled", True) else [n for n in all_names if n not in aito_names]
    try:
        from src.llm_agent import get_agent
        get_agent()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM agent unavailable: {e}")
    try:
        result = run_turn(messages, impls, enabled)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"agent turn failed: {e}")
    result["enabled_tools"] = enabled
    result["cost_usd"] = round(result["cost_usd"], 6)
    return result


@app.get("/api/sales-agent/tools")
def sales_agent_tools():
    from src.sales_agent import tools_public
    return {"tools": tools_public()}


@app.post("/api/sales-agent/chat")
async def sales_agent_chat(request: Request):
    from src.sales_agent import AITO_TOOL_NAMES, TOOLS, run_turn
    return await _agent_chat(request, run_turn, _SALES_TOOL_IMPLS, [t["name"] for t in TOOLS], AITO_TOOL_NAMES)


@app.get("/api/company-agent/tools")
def company_agent_tools():
    from src.company_agent import tools_public
    return {"tools": tools_public()}


@app.post("/api/company-agent/chat")
async def company_agent_chat(request: Request):
    from src.company_agent import AITO_TOOL_NAMES, TOOLS, run_turn
    return await _agent_chat(request, run_turn, _COMPANY_TOOL_IMPLS, [t["name"] for t in TOOLS], AITO_TOOL_NAMES)


@app.get("/api/company-360")
def company_360(industry: str = "", size: str = "", plan: str = ""):
    """The 360 Dashboard — Aito called DIRECTLY (no agent), like the Opportunity
    Assistant. For a customer segment: every KPI with its current rate, the lever
    that moves it most and the projected lift, plus a spotlight at-risk customer
    joined across every domain."""
    seg = {k: v for k, v in {"industry": industry, "size": size, "plan": plan}.items() if v}
    try:
        kpis = []
        for kpi in _KPIS:
            r = _tool_optimize_kpi({"kpi": kpi, **seg})
            if r.get("error"):
                continue
            kpis.append({"key": kpi, **r})  # key = the kpi id; r["kpi"] is its label
        spotlight = None
        rows = (_tool_find_examples({"domain": "customers", **seg, "churned": "yes"}).get("rows") or [])
        if rows:
            spotlight = _tool_customer_360({"customer_id": rows[0].get("customer_id")})
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"segment": seg or "all customers", "kpis": kpis, "customer": spotlight}


# ── Static files — keep this last ─────────────────────────────────

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "out"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
