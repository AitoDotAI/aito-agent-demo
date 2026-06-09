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
        sl = aito.predict("tickets", where, "tool", limit=5, select=["$p", "feature"])
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


# ── Company AI agent — Aito ops over the firm's OWN numbers ─────────
#
# Same machine as the sales agent (src/company_agent.py + agent_core), different
# toolbox: churn/NPS prediction, MRR estimate, account lookup, theme recommendation
# over the `accounts` + `feedback` tables. open_cs_task only ever drafts.

def _acc_where(args: dict) -> dict:
    keys = ["industry", "size", "plan", "tenure_band", "onboarding", "support_load", "usage", "health", "nps_band"]
    return {k: args[k] for k in keys if args.get(k)}


def _fb_where(args: dict) -> dict:
    m = {"industry": "account_industry", "size": "account_size", "plan": "plan", "survey_type": "survey_type"}
    return {col: args[k] for k, col in m.items() if args.get(k)}


def _tool_churn_risk(args: dict) -> dict:
    where = _acc_where(args)
    if not where:
        return {"error": "need at least one account attribute (plan, health, nps_band, tenure…)"}
    hits = aito.predict("accounts", where, "churned", limit=2, select=["$p", "feature", "$why"]).get("hits") or []
    yes = next((h for h in hits if h.get("feature") == "yes"), None)
    return {"churn_probability": round(float(yes["$p"]), 2) if yes else 0.0,
            "drivers": _win_drivers((yes or (hits[0] if hits else {})).get("$why")),
            "based_on": "accounts with these attributes"}


def _tool_nps_drivers(args: dict) -> dict:
    hits = aito.predict("feedback", _fb_where(args), "score_band", limit=3, select=["$p", "feature", "$why"]).get("hits") or []
    det = next((h for h in hits if h.get("feature") == "detractor"), None)
    promo = next((float(h["$p"]) for h in hits if h.get("feature") == "promoter"), 0.0)
    return {"detractor_probability": round(float(det["$p"]), 2) if det else 0.0,
            "promoter_probability": round(promo, 2),
            "drivers": _win_drivers((det or (hits[0] if hits else {})).get("$why")),
            "based_on": "feedback in this segment"}


def _tool_estimate_mrr(args: dict) -> dict:
    where = {k: v for k, v in {"plan": args.get("plan"), "size": args.get("size"),
                               "seats_band": args.get("seats_band"), "industry": args.get("industry")}.items() if v}
    if not where:
        return {"error": "need plan / size / seats to estimate MRR"}
    est = aito.estimate("accounts", where, "mrr_eur").get("estimate")
    if est is None:
        return {"error": "no estimate for that segment"}
    return {"mrr_eur_estimate": round(float(est)), "based_on": "similar accounts"}


def _tool_find_accounts(args: dict) -> dict:
    keys = ["industry", "size", "plan", "health", "churned"]
    where = {k: args[k] for k in keys if args.get(k)}
    rows = (aito.query("accounts", where=where or None,
                       select=["account_id", "industry", "plan", "health", "nps_band", "churned", "mrr_eur"],
                       limit=5).get("hits") or [])
    return {"accounts": [{"account_id": r.get("account_id"), "industry": r.get("industry"), "plan": r.get("plan"),
                          "health": r.get("health"), "nps_band": r.get("nps_band"),
                          "churned": r.get("churned"), "mrr_eur": r.get("mrr_eur")} for r in rows],
            "count": len(rows)}


def _tool_recommend_focus(args: dict) -> dict:
    hits = (aito.recommend("feedback", _fb_where(args), "theme", {"score_band": "promoter"}, limit=4).get("hits") or [])
    return {"themes_to_prioritise": [{"theme": h["feature"], "p": round(float(h["$p"]), 2)} for h in hits]}


def _tool_open_cs_task(args: dict) -> dict:
    return {"status": "draft_created_for_approval", "acted": False,
            "account": args.get("account", "(unspecified)"), "title": args.get("title", ""),
            "note": "CS task drafted for a human to review — nothing was actioned automatically."}


_COMPANY_TOOL_IMPLS = {
    "churn_risk": _tool_churn_risk,
    "nps_drivers": _tool_nps_drivers,
    "estimate_mrr": _tool_estimate_mrr,
    "find_accounts": _tool_find_accounts,
    "recommend_focus": _tool_recommend_focus,
    "open_cs_task": _tool_open_cs_task,
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


# ── Static files — keep this last ─────────────────────────────────

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "out"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
