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

import logging
import contextvars
import functools
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel as _BaseModel

from src import query_log
from src.aito_client import AitoClient, AitoError
from src.gates import ASSIST_GATE, AUTO_GATE
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
log = logging.getLogger(__name__)

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
    query_log.start()  # this request's Aito queries, for the side panel (see _with_queries)
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
# light per-IP sliding-window cap as abuse insurance. In-memory is fine — one
# uvicorn process, and a demo doesn't need a shared store.
_LLM_PATHS = {"/api/resolve-llm", "/api/route", "/api/sales-agent/chat", "/api/company-agent/chat",
              "/api/support/reply"}
_RL_MAX = 20          # requests
#: tighter per-path caps: a support reply can be two LLM calls and takes free text
_RL_MAX_BY_PATH = {"/api/support/reply": 6}
_RL_WINDOW = 60.0     # seconds
_rl_hits: dict[str, list[float]] = {}
#: proxies that APPEND to X-Forwarded-For in front of the app: Azure's front end, then
#: nginx ($proxy_add_x_forwarded_for). Entries left of those are whatever the client sent,
#: so the client is the entry that many hops from the right, never the first one.
_PROXY_HOPS = int(os.environ.get("RATE_LIMIT_PROXY_HOPS", "2"))


def _bare_ip(addr: str) -> str:
    """The address without a port: App Service's front end may send "IP:PORT", which would
    give every TCP connection its own bucket. "[v6]:port" -> "v6"; a bare IPv6 stays as is."""
    if addr.startswith("["):
        return addr[1:addr.index("]")] if "]" in addr else addr.strip("[]")
    if addr.count(":") == 1:
        return addr.split(":")[0]
    return addr


def _client_ip(request: Request) -> str:
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    ip = _bare_ip(hops[-min(_PROXY_HOPS, len(hops))]) if hops else ""
    # a malformed entry ("[", ":80") must not put its senders into one shared bucket
    return ip or (request.client.host if request.client else "anon")


def _over_limit(request: Request, key_path: str, limit: int) -> bool:
    """Record one hit for this client on key_path; True when it is over `limit` a minute."""
    now = time.monotonic()
    key = f"{_client_ip(request)} {key_path}"
    recent = [t for t in _rl_hits.get(key, []) if now - t < _RL_WINDOW]
    if len(recent) >= limit:
        return True
    recent.append(now)
    _rl_hits[key] = recent
    if len(_rl_hits) > 5000:  # bound memory: drop anyone with no live hits
        for k in [k for k, v in list(_rl_hits.items()) if not any(now - t < _RL_WINDOW for t in v)]:
            _rl_hits.pop(k, None)
    return False


@app.middleware("http")
async def rate_limit_llm(request: Request, call_next):
    path = request.url.path
    if path in _LLM_PATHS:
        if _over_limit(request, path if path in _RL_MAX_BY_PATH else "llm", _RL_MAX_BY_PATH.get(path, _RL_MAX)):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "Too many AI requests from your network. Give it a few seconds."},
                status_code=429,
            )
    return await call_next(request)


def _with_queries(fn):
    """Return the Aito queries a route sent as `_queries`, so its side panel shows the
    query actually sent (src/query_log.py). Body, op, path and env only; no credentials."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        out = fn(*args, **kwargs)
        if isinstance(out, dict) and "_queries" not in out:
            out = {**out, "_queries": query_log.current()}
        return out
    return wrapper


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
    """Yield (field, value) pairs from a _why proposition.

    Handles conjunction nesting in both encodings: v1 groups ANDed
    propositions under `$and`, v2 (Rep2) under `$group`. Missing `$group`
    is a silent drop, not an error — the list value matches neither branch
    below, so the factor would render with no conditions at all.
    """
    if not isinstance(prop, dict):
        return
    for conjunction in ("$and", "$group"):
        if conjunction in prop:
            for sub in prop[conjunction] or []:
                yield from _why_props(sub)
            return
    for field, cond in prop.items():
        if isinstance(cond, dict):
            for _op, val in cond.items():
                yield field, val
        elif isinstance(cond, (str, int, float, bool)):
            # v2 _relate states propositions as bare values ({"plan": "Free"})
            # where v1 wrapped them in an operator ({"plan": {"$has": "Free"}}).
            yield field, cond


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
@_with_queries
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
        raw_why = _why_of(intent_resp.get("hits") or [], intent)
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

#: longest visitor text an LLM demo route takes (the samples are under 120 characters)
_LLM_TEXT_MAX = 400


class LLMText(_BaseModel):
    text: str
    sender: str = ""


def _llm_guard(text: str) -> None:
    """Before any LLM call on a public route: a length cap and today's shared budget."""
    from src.llm_agent import budget_left
    if not text.strip() or len(text) > _LLM_TEXT_MAX:
        raise HTTPException(status_code=422, detail=f"Write the message in 1 to {_LLM_TEXT_MAX} characters.")
    if budget_left() <= 0:
        raise HTTPException(status_code=429, detail="The live LLM side of this demo is paused for today "
                                                    "(its daily budget is used up). Aito's side still works.")


@app.post("/api/resolve-llm")
def resolve_llm(req: LLMText):
    """Resolve the SAME ticket with a live gpt-5-mini call, so the UI can show the
    real latency/cost next to Aito's instant prediction. One structured call —
    the generous baseline (a real tool-calling agent would chain several).
    POST, so no crawler or link preview spends a call."""
    from src.llm_agent import cost_usd, get_agent, spend

    text = req.text
    _llm_guard(text)

    try:
        agent = get_agent()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"LLM agent unavailable: {e}")
    try:
        r = agent.resolve(text)
    except Exception as e:  # noqa: BLE001 — surface any LLM failure as 502
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")
    spend(r.input_tokens + r.output_tokens)
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
    "Hi, please refund the €45 charge on my roaming pack.",
]
_TEAM = {
    "refund": "Billing", "check_balance": "Billing", "check_outage": "Network Ops",
    "repair_help": "Tech Support", "cancel_service": "Retention", "find_shop": "Sales",
}
_SENSITIVE = {"refund", "cancel_service"}
#: the off-topic ticket the Human handoff page's caveat quotes; its read is measured live
_CAVEAT_EXAMPLE = "What's the weather like in Oulu tomorrow?"
_AUTO_GATE, _ASSIST_GATE = AUTO_GATE, ASSIST_GATE  # src/gates.py: one place for the whole app


@app.get("/api/handoff")
@_with_queries
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
                band, reason = "handoff", f"low confidence ({p*100:.0f}%), Aito won't guess on this"
            elif intent in _SENSITIVE:  # confident, but money/state-change → verify with a human
                band, reason = "handoff", f"sensitive action ({intent.replace('_', ' ')}), needs human verification"
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
    try:
        ex_intent, ex_p, _ = _top_and_alts(aito.predict("resolutions", {"text": _CAVEAT_EXAMPLE}, "intent",
                                                         limit=3, select=["$p", "feature"]))
        example = {"text": _CAVEAT_EXAMPLE, "intent": ex_intent, "p": round(ex_p, 2)}
    except AitoError:
        example = None
    return {"total": len(rows), "counts": counts, "handoff": [r for r in rows if r["band"] == "handoff"],
            "caveat_example": example}


# ── Cooperation: Aito short-lists, the LLM decides ────────────────

import json as _json

_CATALOG = _json.loads((Path(__file__).resolve().parent / "tools_catalog.json").read_text())
_CATALOG_BY_NAME = {t["name"]: t for t in _CATALOG}


@app.post("/api/route")
@_with_queries
def route(req: LLMText):
    """Augmentation demo (short-listing). Aito `_predict` shortlists the few tools
    that history says are relevant; the SAME LLM then picks — once over the whole
    catalog (alone) and once over Aito's shortlist (cooperation) — so you can see
    that Aito makes the model faster/cheaper/grounded rather than replacing it.
    POST, so no crawler or link preview spends a call."""
    from src.llm_agent import cost_usd, get_agent, spend

    text = req.text
    _llm_guard(text)
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
        spend(r.input_tokens + r.output_tokens)
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


def _play(ch: list, ang: list, per: list) -> dict:
    """The outreach play Aito recommends: its top channel, angle and personalization,
    or None where _recommend returned nothing (never a made-up default)."""
    top = lambda hits: hits[0]["feature"] if hits else None  # noqa: E731
    return {"channel": top(ch), "angle": top(ang), "personalization": top(per)}

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
@_with_queries
def opportunity(industry: str = "SaaS", client_size: str = "Mid-market", service_line: str = "Data Platform",
                deal_size_band: str = "L", region: str = "Helsinki", lead_source: str = "Inbound",
                complexity: str = "Medium", team_seniority: str = "balanced", relationship: str = "New logo",
                competitive: str = "Competitive", target_role: str = "Head of Data"):
    """One deal sheet from the firm's history: win-likelihood (+ drivers), an
    effort/cost estimate, reference projects to cite, and the outreach most likely
    to land, with its meeting rate against the baseline for the same target. The
    outreach is always a draft for the rep; nothing here sends."""
    eng_where = {"client_industry": industry, "client_size": client_size, "service_line": service_line,
                 "deal_size_band": deal_size_band, "complexity": complexity, "team_seniority": team_seniority,
                 "lead_source": lead_source, "relationship": relationship, "competitive": competitive, "region": region}
    try:
        wr = aito.predict("engagements", eng_where, "outcome", limit=2, select=["$p", "feature", "$why"])
        whits = wr.get("hits") or []
        won_p = _p_of(whits, "won")
        drivers = _win_drivers(_why_of(whits, "won"))

        er = aito.estimate("engagements", {"service_line": service_line, "deal_size_band": deal_size_band,
                                            "complexity": complexity, "team_seniority": team_seniority,
                                            "client_industry": industry}, "effort_days")
        effort = round(float(er.get("estimate", 0)))

        refs = _distinct_refs({"client_industry": industry, "service_line": service_line, "outcome": "won"})

        out_where = {"target_industry": industry, "target_role": target_role}
        ch = (aito.recommend("outreach", out_where, "channel", {"meeting": "yes"}, limit=4).get("hits") or [])
        ang = (aito.recommend("outreach", out_where, "angle", {"meeting": "yes"}, limit=5).get("hits") or [])
        per = (aito.recommend("outreach", out_where, "personalization", {"meeting": "yes"}, limit=3).get("hits") or [])
        play = _play(ch, ang, per)
        # the projection uses only what Aito recommended; nothing is assumed for the rest
        meeting_p = _meeting_p({**out_where, **play}) if None not in play.values() else None
        baseline_p = _meeting_p(out_where)
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
        "win": {"p": won_p, "drivers": drivers, "base_rate": _base_win_rate()},
        "effort_days": effort,
        "references": [{"brief": r.get("brief"), "effort_days": r.get("effort_days"),
                        "deal_size_band": r.get("deal_size_band"), "region": r.get("region")} for r in refs],
        "outreach": {
            "channels": [{"v": h["feature"], "p": float(h["$p"])} for h in ch],
            "angles": [{"v": h["feature"], "p": float(h["$p"])} for h in ang],
            "recommended": play,
            "meeting_p": meeting_p,
            "baseline_meeting_p": baseline_p,
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


_BASE_WIN_CACHE: dict = {"at": 0.0, "rate": None}


def _base_win_rate() -> float | None:
    """The share of all pursued engagements that were won, counted (cached ten minutes):
    the base a deal's win odds are read against."""
    if time.time() - _BASE_WIN_CACHE["at"] > 600 or _BASE_WIN_CACHE["rate"] is None:
        try:
            total = aito.query("engagements", limit=0).get("total") or 0
            won = aito.query("engagements", where={"outcome": "won"}, limit=0).get("total") or 0
        except AitoError:
            return _BASE_WIN_CACHE["rate"]  # the odds still show; only the comparison is missing
        _BASE_WIN_CACHE.update(at=time.time(), rate=round(won / total, 3) if total else None)
    return _BASE_WIN_CACHE["rate"]


def _tool_win_odds(args: dict) -> dict:
    where = _eng_where(args)
    if not where:
        return {"error": "need at least one field (industry, service_line, lead_source, …) to read win odds"}
    r = aito.predict("engagements", where, "outcome", limit=2, select=["$p", "feature", "$why"])
    hits = r.get("hits") or []
    won_p = _p_of(hits, "won")
    base = _base_win_rate()
    return {
        "win_probability": round(won_p, 2),
        "base_win_rate": base,  # quote the odds against this: the lift over the base is the story
        "times_the_base": round(won_p / base, 1) if base else None,
        "drivers": _win_drivers(_why_of(hits, "won")),
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


def _distinct_refs(where: dict, n: int = 3) -> list[dict]:
    """Up to n won references that describe different work, so a card never lists the
    same project three times (briefs read "<client>: <work>.")."""
    hits = aito.query("engagements", where=where, select=["brief", "effort_days", "deal_size_band", "region"],
                      limit=n * 4).get("hits") or []
    out, works = [], set()
    for h in hits:
        work = str(h.get("brief", "")).split(": ", 1)[-1]
        if work not in works:
            works.add(work)
            out.append(h)
        if len(out) == n:
            break
    return out


def _tool_find_references(args: dict) -> dict:
    where = {"outcome": "won"}
    if args.get("industry"):
        where["client_industry"] = args["industry"]
    if args.get("service_line"):
        where["service_line"] = args["service_line"]
    refs = _distinct_refs(where)
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
    per = (aito.recommend("outreach", where, "personalization", {"meeting": "yes"}, limit=3).get("hits") or [])
    play = _play(ch, ang, per)
    # recommended approach vs the baseline = expected meeting rate for this target
    # WITHOUT optimising the approach (the prior). The ratio is the live "outcome lift".
    # Only what Aito recommended goes into the projection; no recommendation, no projection.
    rec_p = _meeting_p({**where, **play}) if None not in play.values() else None
    base_p = _meeting_p(where)
    lift = round(rec_p / base_p, 1) if rec_p is not None and base_p > 0 else None
    return {**play,
            "meeting_probability": round(rec_p, 2) if rec_p is not None else None,
            "baseline_meeting_probability": round(base_p, 2),
            "outcome_lift": lift}  # rec / baseline: how many times more meetings than not optimising


def _tool_propose_send_email(args: dict) -> dict:
    # Never sends. Always returns a draft-queued status for human approval.
    return {"status": "draft_queued_for_approval", "sent": False,
            "to": args.get("to", "(unspecified)"), "subject": args.get("subject", ""),
            "note": "Draft saved for the rep to review and send. Nothing was sent automatically."}


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


def _why_target(why_node):
    """The value a `$why` explains: the value in its `baseP` proposition.

    `{"type": "baseP", "proposition": {"outcome": {"$has": "won"}}}` → "won".
    None when the tree has no baseP to read.
    """
    leaves: list = []
    _flatten_why(why_node, leaves)
    for leaf in leaves:
        if leaf.get("type") == "baseP":
            for _field, value in _why_props(leaf.get("proposition", {})):
                return value
    return None


def _why_of(hits: list, feature: str):
    """The `$why` of the hit predicting `feature`, never another hit's.

    Taking `hits[0]["$why"]` is only right when hits[0] is the value being
    shown. Under a win probability it is not: hits[0] is `lost` whenever the
    odds are below 50%, and its drivers are the drivers of LOSING, rendered
    as reasons to win. That shipped (the 2026-09 $why integrity audit,
    "index coupling").

    If the hit's own explanation names a different target, the explanation
    is DROPPED (None) and logged, never moved: a missing explanation is
    honest, a wrong one is not. Dropping rather than raising keeps one bad
    explanation from 502-ing a whole dashboard or agent turn.
    """
    hit = next((h for h in hits if h.get("feature") == feature), None)
    why = (hit or {}).get("$why")
    if not why:
        return None
    target = _why_target(why)
    if target is not None and str(target).lower() != str(feature).lower():
        log.warning("$why explains %r but would render under %r; dropped", target, feature)
        return None
    return why


# structural / identity fields that are never useful "causes"
_NON_CAUSE = {"mrr_eur", "name", "primary_product", "product", "duration_weeks", "brief", "customer", "region"}


def _is_cause_field(field: str, exclude: set[str]) -> bool:
    return field not in exclude and field not in _NON_CAUSE and not field.endswith("_id") and not field.endswith("Id")


def _relate_drivers(table: str, target_field: str, bad: str, seg_props: list[dict],
                    exclude: set[str], candidates: list[str], k: int = 3,
                    failed: list | None = None) -> list[dict]:
    """Root causes of the BAD outcome. With a segment, _relate `$on` scopes to it and
    returns each driver's WITHIN-SEGMENT outcome RATE (e.g. Red-health customers churn
    at 44% vs 28% otherwise → mode 'rate'). With no segment, relate globally and return
    the SHARE of the bad outcome carrying each value (mode 'share'). Strongest factors
    by |lift-1| (drivers >1 and protective <1), one per field. An Aito error returns []
    so the page still renders, and is recorded in `failed`, so "no driver" and "the
    query failed" stay distinguishable (the live smoke asserts on it)."""
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
    except AitoError as e:
        print(f"_relate_drivers {table}.{target_field} failed: {e}")
        if failed is not None:
            failed.append(str(e))
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
    # The segment is the POPULATION: a segment in `where` is only evidence, so the prior, the
    # lever ranking and the projection would still come from every customer. `pop` scopes them.
    pop = {"from": table, "where": where} if where else table
    # the current rates are counted within the segment, not modelled
    total = aito.query(table, where=where or None, limit=0).get("total") or 0
    if total == 0:
        # an empty segment is an empty state, not an error: on shared 2.11.x a nested `from`
        # matching no rows answers 400 instead of an empty result (td-20261001101027850797)
        return _empty_kpi(cfg, lower_better)
    good_n = aito.query(table, where={**where, target: good}, limit=0).get("total") or 0
    current = round(good_n / total, 2)
    # $why from the pooled model: it explains how this segment's attributes move the rate
    # relative to every customer (the "?" next to the headline), not the rate itself
    hits = aito.predict(table, where, target, limit=4, select=["$p", "feature", "$why"]).get("hits") or []
    # KPI RATE $why: explain the rate itself from the segment attributes' lifts
    # (base 23% × Free ×1.5 = 35%) — the "?" next to the headline number.
    kpi_why = _kpi_why(_why_of(hits, focus))
    # CAUSES (diagnosis): _relate the BAD outcome to all fields, scoped to the segment
    # via $on — within-segment driver RATES; two-sided (drivers >1, protective <1).
    seg_props = [{f: v} for f, v in where.items()]
    exclude = {target, cfg["lever"], "industry", "size", "plan"}
    failed: list = []
    causes = _relate_drivers(table, target, bad, seg_props, exclude, cfg["causes"], k=3, failed=failed)
    # LEVERS (prescription): _recommend ranks the lever values toward the goal (it
    # conditions properly, unlike relating the good outcome). Each is shown as a lift
    # = P(good | this lever) / the segment's current good-rate.
    rec = _unless_empty(lambda: aito.recommend(pop, {}, cfg["lever"], {target: good}, limit=3).get("hits") or [])
    lever_items = []
    for h in rec:
        p = round(float(h["$p"]), 2)
        lever_items.append({"value": h["feature"], "p": p,
                            "lift": round(p / current, 2) if current > 0 else 1.0})
    best = lever_items[0]["value"] if lever_items else None
    ph: list = []
    projected = current
    if best is not None:
        ph = _unless_empty(lambda: aito.predict(pop, {cfg["lever"]: best}, target, limit=4,
                                                 select=["$p", "feature"]).get("hits") or [])
        projected = round(_p_of(ph, good), 2) if ph else current
    report_n = aito.query(table, where={**where, target: report}, limit=0).get("total") or 0 if lower_better else 0
    now = (round(report_n / total, 2) if total else 0.0) if lower_better else current
    then = (round(_p_of(ph, report), 2) if (lower_better and best is not None and ph) else (now if lower_better else projected))
    return {
        "kpi": cfg["label"], "goal": f"{target}={good}",
        "headline": {"metric": cfg["label"], "now": now, "then": then, "lower_is_better": lower_better},
        "current": current,
        "current_basis": f"counted: {good_n} of {total} {cfg['good_label']} in the {'segment' if where else 'base'}",
        "bad_label": cfg["bad_label"], "good_label": cfg["good_label"],
        "kpi_why": kpi_why,   # base × segment-attribute lifts = the rate
        "causes": causes, "drivers": causes,   # within-segment drivers ($on _relate)
        **({"causes_unavailable": "Aito could not compute the causes just now"} if failed else {}),
        "levers": {"lever": cfg["lever_label"], "items": lever_items},  # condition = the good outcome
        "recommended_play": {"lever": cfg["lever_label"], "change_to": best},
        "projected": projected,
        "lift_pp": round(abs(then - now) * 100),
        "note": "Aito has no training step: log this play's outcome and it sharpens the next prediction.",
    }


def _empty_kpi(cfg: dict, lower_better: bool) -> dict:
    """A KPI over a segment with no rows: nothing to count, explain or recommend."""
    return {"kpi": cfg["label"], "goal": f"{cfg['target']}={cfg['good']}", "empty": True,
            "headline": {"metric": cfg["label"], "now": None, "then": None, "lower_is_better": lower_better},
            "current": None, "current_basis": f"no {cfg['good_label'].split()[-1]} in this segment",
            "bad_label": cfg["bad_label"], "good_label": cfg["good_label"], "kpi_why": {"base": None, "factors": []},
            "causes": [], "drivers": [], "levers": {"lever": cfg["lever_label"], "items": []},
            "recommended_play": {"lever": cfg["lever_label"], "change_to": None}, "projected": None, "lift_pp": 0,
            "note": "This segment has no rows for this KPI."}


def _unless_empty(call):
    """A nested-`from` call, where the engine's "matched no rows" 400 means an empty population."""
    try:
        return call()
    except AitoError as e:
        body = e.body if isinstance(e.body, dict) else {}
        if e.status_code == 400 and "matched no rows" in str((body.get("data") or {}).get("message", "")):
            return []
        raise


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
    out = {"profile": {k: profile.get(k) for k in
                       ("customer_id", "name", "industry", "size", "plan", "health", "nps_band",
                        "csm_motion", "mrr_eur", "churned")},
           "domains": domains}
    if aito._ver == "v2":
        failed: list = []
        out["graph"] = _customer_neighbourhood(cid, failed)
        if failed:
            out["graph_unavailable"] = True
    return out


#: The customer's whole linked neighbourhood in ONE v2 _query: `$refs.<table>.customer.<field>`
#: walks each link backwards (every ticket, deal, ... pointing at this customer) and
#: `$distinctLength` counts independent sources (4 ticket channels, not 6 tickets).
_NEIGHBOURHOOD_SELECT = [
    {"tickets": "$refs.tickets.customer.csat_band"},
    {"ticket_channels": {"$distinctLength": "$refs.tickets.customer.channel"}},
    {"usage_active": "$refs.usage.customer.active"},
    {"distinct_products": {"$distinctLength": "$refs.usage.customer.product"}},
    {"deals": "$refs.deals.customer.converted"},
    {"invoices": "$refs.invoices.customer.status"},
    {"feedback": "$refs.feedback.customer.score_band"},
    {"feedback_channels": {"$distinctLength": "$refs.feedback.customer.channel"}},
]


def _customer_neighbourhood(cid: str, failed: list | None = None) -> dict | None:
    """Retrieval and provenance only. On this dataset none of these facts moves churn
    (docs/verification/company-graph.md), so never present them as drivers."""
    try:  # an optional add-on: without it the spotlight still shows profile + domains
        hits = aito.query("customers", where={"customer_id": cid},
                          select=_NEIGHBOURHOOD_SELECT, limit=1).get("hits") or []
    except AitoError as e:
        print(f"customer neighbourhood unavailable for {cid}: {e}")
        if failed is not None:
            failed.append(str(e))
        return None
    if not hits:
        return None
    h = hits[0]
    n = lambda k, v: sum(1 for x in h.get(k) or [] if x == v)  # noqa: E731
    return {
        "tickets": {"count": len(h.get("tickets") or []), "bad_csat": n("tickets", "bad"),
                    "channels": h.get("ticket_channels") or 0},
        "usage": {"products": h.get("distinct_products") or 0, "active": n("usage_active", "yes")},
        "deals": {"count": len(h.get("deals") or []), "won": n("deals", "yes")},
        "invoices": {"count": len(h.get("invoices") or []), "overdue": n("invoices", "overdue")},
        "feedback": {"count": len(h.get("feedback") or []), "detractor": n("feedback", "detractor"),
                     "channels": h.get("feedback_channels") or 0},
        "note": "Facts retrieved through the links, not predictions: on this data they do not move churn.",
    }


def _tool_find_examples(args: dict) -> dict:
    domain = args.get("domain")
    if domain not in _KPIS and domain not in ("customers",) and domain not in _360_SELECT:
        return {"error": f"unknown domain '{domain}'"}
    where = _seg_where(domain, args)
    if domain == "customers":
        for f in ("churned", "health"):
            if args.get(f):
                where[f] = args[f]
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
            "note": "Play drafted for a human to approve. Nothing was run automatically."}


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
@_with_queries
def company_360(industry: str = "", size: str = "", plan: str = ""):
    """The 360 Dashboard — Aito called DIRECTLY (no agent), like the Opportunity
    Assistant. For a customer segment: every KPI with its current rate, the lever
    that moves it most and the projected lift, plus a spotlight at-risk customer
    joined across every domain."""
    seg = {k: v for k, v in {"industry": industry, "size": size, "plan": plan}.items() if v}

    def spotlight_of():
        # "at risk" means still a customer: someone who has not churned, with the strongest
        # observable risk (health Red is the largest measured churn driver), else Yellow, else any
        for health in ("Red", "Yellow", None):
            rows = (_tool_find_examples({"domain": "customers", **seg, "churned": "no",
                                         **({"health": health} if health else {})}).get("rows") or [])
            if rows:
                found = _tool_customer_360({"customer_id": rows[0].get("customer_id")})
                found["why_spotlight"] = (f"a current customer (not churned) with health {health}" if health
                                          else "a current customer (not churned); none in this segment is Red or Yellow")
                return found
        return None

    # the six KPIs and the spotlight are independent: run them at once, each in a copy of this
    # request's context so the side panel still records their queries; KPI order is kept
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(_KPIS) + 1) as pool:
        futures = {kpi: pool.submit(contextvars.copy_context().run, _tool_optimize_kpi, {"kpi": kpi, **seg})
                   for kpi in _KPIS}
        spot_future = pool.submit(contextvars.copy_context().run, spotlight_of)
        try:
            kpis = []
            for kpi, f in futures.items():
                r = f.result()
                if r.get("error"):
                    continue
                kpis.append({"key": kpi, **r})  # key = the kpi id; r["kpi"] is its label
            spotlight = spot_future.result()
        except AitoError as e:
            raise HTTPException(status_code=502, detail=str(e))
    # the parts that fell back to empty on an Aito error, so a hollow view is visible as one
    degraded = [f"causes:{k['key']}" for k in kpis if k.get("causes_unavailable")]
    if spotlight and spotlight.get("graph_unavailable"):
        degraded.append("graph")
    return {"segment": seg or "all customers", "kpis": kpis, "customer": spotlight, "degraded": degraded}


# ── Governance: the rules the agent's decisions follow (use case #15) ──
# Read-only. The rule objects follow aito-accounting-demo's promote API (ADR 0025),
# plus an `op` per condition; the writable version adds POST /api/rules/promote and
# /demote. ADR 0025 keys rules by customer_id (tenant); here the key is the log.

_GOV_CACHE: dict[str, dict] = {}  # the decision logs are static seed data: mine once per process


@app.get("/api/governance/rules")
@_with_queries
def governance_rules(log: str = "resolutions"):
    from src.governance import LOGS, mine_rules
    if log not in LOGS:
        raise HTTPException(status_code=400, detail=f"log must be one of {sorted(LOGS)}")
    if log not in _GOV_CACHE:
        try:
            _GOV_CACHE[log] = mine_rules(aito, log)
        except AitoError as e:
            raise HTTPException(status_code=502, detail=str(e))
    return {**_GOV_CACHE[log], "logs": {k: v["label"] for k, v in LOGS.items()}}


@app.get("/api/rules/active")
@_with_queries
def rules_active(log: str = "resolutions"):
    """The promoted rules in force. None yet: promotion needs a writable engine,
    so no decision is made by a rule; the model path decides (see RulesView)."""
    return {"log": log, "rules": [], "writable": False,
            "note": "Read-only demo: no rule has been promoted, so no decision is made by a rule."}


# ── Support agent: the predictive envelope (docs/design/support-agent.md) ──
# Read-only, over the `support` fixture. Its tables live in a branch environment
# until they are promoted, so this is its own v2 client: AITO_SUPPORT_ENV names the
# environment ("support" by default; empty means master, once promoted).

_SUPPORT_ENV = os.environ.get("AITO_SUPPORT_ENV", "support").strip() or None
_support_aito: AitoClient | None = None
_support_state: dict = {"checked": 0.0, "loaded": False}


def _support_client() -> AitoClient:
    global _support_aito
    if _support_aito is None:
        from src.config import Config
        root = config.aito_url.split("/env/")[0]
        url = f"{root}/env/{_SUPPORT_ENV}" if _SUPPORT_ENV else root
        _support_aito = AitoClient(Config(aito_url=url, aito_key=config.aito_key,
                                          aito_api_version="v2", aito_env=_SUPPORT_ENV))
    return _support_aito


def _support_loaded() -> bool:
    """Whether the fixture is in the support environment; re-checked at most once a minute."""
    if time.time() - _support_state["checked"] > 60:
        try:
            tables = _support_client().get_schema().get("schema", {})
            _support_state["loaded"] = {"support_tickets", "support_steps", "customers"} <= set(tables)
            _support_state["checked"] = time.time()
        except AitoError:  # a blip: say "not loaded" now, but look again in 10 s, not 60
            _support_state["loaded"] = False
            _support_state["checked"] = time.time() - 50
    return _support_state["loaded"]


@app.get("/api/support/status")
def support_status():
    return {"loaded": _support_loaded(), "env": _SUPPORT_ENV or "master"}


@app.get("/api/support/incoming")
def support_incoming():
    """The held-out queue: tickets never loaded into Aito (served from the app, not Aito)."""
    from src.support_envelope import load_incoming
    q = load_incoming()
    return {"tickets": [{k: q["tickets"][i][k] for k in ("ticket_id", "created_at", "text", "channel")}
                        for i in reversed(q["order"])]}


#: what the envelope reads for a ticket; truth fields are blanked when the text is edited
_TRUTH = ("customer", "product", "category", "priority", "resolution", "kb_article", "nps_after",
          "upsell_accepted", "upsell_offered")
#: envelopes already run, so the reply reuses the calls the page just made
_envelopes: dict[tuple[int, str, str | None], dict] = {}


def _support_ticket(ticket_id: str, text: str | None) -> tuple[dict, list]:
    from src.support_envelope import load_incoming
    q = load_incoming()
    if ticket_id not in q["tickets"]:
        raise HTTPException(status_code=404, detail=f"no incoming ticket {ticket_id}")
    t = q["tickets"][ticket_id]
    if text is None or text.strip() == t["text"]:
        return t, q["steps"].get(ticket_id, [])
    text = text.strip()
    if not text or len(text) > 600:
        raise HTTPException(status_code=422, detail="Write the ticket in 1 to 600 characters.")
    # your own words from the same sender: nothing recorded happened to them, so no truth
    return {**t, "text": text, **{k: None for k in _TRUTH}}, []


def _envelope_for(ticket_id: str, text: str | None) -> dict:
    from src.support_envelope import envelope
    ticket, steps = _support_ticket(ticket_id, text)
    if not _support_loaded():
        raise HTTPException(status_code=503, detail="The support fixture is not loaded in this environment yet.")
    key = (id(_support_client()), ticket_id, None if ticket["customer"] is not None else ticket["text"])
    cached = _envelopes.get(key)
    if cached is not None:
        return cached
    before = len(query_log.current())
    try:
        out = envelope(_support_client(), ticket, steps)
    except AitoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    out["_queries"] = query_log.current()[before:]  # cached with the value, so a cache hit shows them too
    out["edited"] = key[2] is not None
    if out["edited"]:
        for s in out["steps"]:
            if "happened" in s:
                s["happened"] = None
    if not out.get("degraded"):  # a step that failed once is retried next time, not remembered
        if len(_envelopes) > 500:
            _envelopes.clear()
        _envelopes[key] = out
    return out


#: visitor-written text runs ~11 uncached Aito calls; this caps it per client
_ENVELOPE_TEXT_PER_MIN = 10


@app.get("/api/support/envelope")
@_with_queries
def support_envelope(request: Request, ticket_id: str, text: str | None = None):
    if text is not None and _over_limit(request, "/api/support/envelope?text", _ENVELOPE_TEXT_PER_MIN):
        raise HTTPException(status_code=429, detail="Too many of your own tickets in a minute. Give it a few seconds.")
    return _envelope_for(ticket_id, text)


class ReplyRequest(_BaseModel):
    ticket_id: str
    text: str | None = None
    stronger: bool = False


#: the stronger model's reads can hold a worker for up to 120 s: at most this many at once,
#: so they can't use up the thread pool the rest of the app (and /health) runs on
_STRONG_SLOTS = threading.BoundedSemaphore(int(os.environ.get("SUPPORT_STRONG_CONCURRENCY", "2")))


@app.post("/api/support/reply")
def support_reply(req: ReplyRequest):
    """The LLM's half: a reply from Aito's decisions, through code guards (src/support_reply.py)."""
    from src.support_envelope import load_incoming
    from src.support_reply import draft_reply
    env = _envelope_for(req.ticket_id, req.text)
    step = {s["key"]: s for s in env["steps"]}
    kb = None
    if step["kb"].get("value"):
        try:
            hits = _support_client().query(table="kb_articles", where={"article_id": step["kb"]["value"]},
                                           select=["article_id", "title", "body"], limit=1).get("hits") or []
        except AitoError as e:
            raise HTTPException(status_code=502, detail=str(e))
        kb = hits[0] if hits else None
    from openai import OpenAIError
    options = sorted({t["resolution"] for t in load_incoming()["tickets"].values()})
    if req.stronger and not _STRONG_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="The stronger model is busy with other readers. Try again in a minute.")
    try:
        return draft_reply(env, kb, step["customer"].get("contact"), options, stronger=req.stronger)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"{e}. The earlier read stands.")
    except (RuntimeError, OpenAIError) as e:
        raise HTTPException(status_code=503, detail=f"The LLM is not available: {type(e).__name__}")
    finally:
        if req.stronger:
            _STRONG_SLOTS.release()


_BENCH = Path(__file__).resolve().parent.parent / "scripts" / "support_fixture" / "results" / "compare_modes.json"


@app.get("/api/support/benchmark")
def support_benchmark():
    """The recorded Aito vs LLM comparison on the held-out queue (scripts/support_fixture/compare_modes.py),
    with its re-score on the tickets whose wording is new (novel_text.py)."""
    if not _BENCH.exists():
        raise HTTPException(status_code=404, detail="no recorded comparison")
    out = _json.loads(_BENCH.read_text())
    novel = _BENCH.with_name("novel_text.json")
    if novel.exists():
        out["novel_text"] = _json.loads(novel.read_text())
    return out


# ── Static files — keep this last ─────────────────────────────────

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "out"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
