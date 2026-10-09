"""The OpenAI Decisions API arm (`POST /v1/decisions`, public beta 2026-10-06), self-contained like
llm.py so it can be reproduced with your own key.

One `choice` question per message, over the same intent labels the other arms see. The key comes
from OPENAI_API_KEY in the environment only; OPENAI_BASE_URL overrides https://api.openai.com/v1.
The answer's `confidence` is the stated probability (scored for calibration like Aito's $p).

Request/response shapes are from https://developers.openai.com/api/docs/guides/decisions, read
2026-10-07. The guide documents no `usage` field, so tokens are read from the response when it
has one and otherwise estimated from the request (flagged per answer as `tokens_estimated`).
"""

from __future__ import annotations

import json
import os
import time

import httpx

#: USD per 1M input tokens; output is not charged (the Decisions guide: "You pay only for input tokens")
DECISIONS_PRICES = {
    "gpt-6-luna": {"in": 0.10, "out": 0.0, "source": "https://developers.openai.com/api/docs/guides/decisions, read 2026-10-07"},
}
_RETRY = {408, 409, 429, 500, 502, 503, 504}


def usd(model: str, i: int, o: int = 0) -> float | None:
    p = DECISIONS_PRICES.get(model)
    return None if p is None else i / 1e6 * p["in"] + o / 1e6 * p["out"]


def request_body(model: str, instructions: str, text: str, allowed: list[str], name: str = "intent") -> dict:
    return {"model": model, "input": text,
            "questions": [{"type": "choice", "name": name, "instructions": instructions,
                           "choices": [{"value": a} for a in allowed]}]}


def estimate_tokens(body: dict) -> int:
    """Input tokens of a request: tiktoken's o200k_base over the JSON when it is installed, else
    characters / 4. An estimate either way: how the endpoint counts a `questions` block is not documented."""
    s = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    try:
        import tiktoken
        return len(tiktoken.get_encoding("o200k_base").encode(s))
    except Exception:  # noqa: BLE001  (tiktoken missing, or its vocabulary not downloadable offline)
        return len(s) // 4


def parse(answer: dict, allowed: list[str]) -> dict:
    """One answer object -> pred, p (the stated confidence) and the top of its probabilities."""
    if answer.get("type") != "choice":      # a refusal, or a shape this harness does not know
        return {"pred": None, "raw": answer.get("type"), "p": None, "top": []}
    choice = answer.get("choice")
    top = sorted(({"intent": x.get("value"), "p": round(float(x.get("probability", 0.0)), 4)}
                  for x in answer.get("probabilities") or []), key=lambda t: -t["p"])[:5]
    conf = answer.get("confidence")
    return {"pred": choice if choice in allowed else None, "raw": None if choice in allowed else choice,
            "p": round(float(conf), 4) if conf is not None else (top[0]["p"] if top else None), "top": top}


def target() -> tuple[str, dict, str]:
    """Where the call goes: OpenAI with OPENAI_API_KEY, else the Azure OpenAI resource the other
    LLM arms use (OPENAI_MODEL_URL + OPENAI_MODEL_API_KEY, its v1 API; the model is the deployment)."""
    if os.environ.get("OPENAI_API_KEY"):
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        return base + "/decisions", {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}, "OpenAI"
    url, key = os.environ.get("OPENAI_MODEL_URL"), os.environ.get("OPENAI_MODEL_API_KEY")
    if url and key:
        return url.rstrip("/") + "/openai/v1/decisions", {"api-key": key}, "Azure OpenAI"
    raise SystemExit("no key: set OPENAI_API_KEY, or OPENAI_MODEL_URL + OPENAI_MODEL_API_KEY for Azure "
                     "(environment or the repo's dotenv file)")


def decide(model: str, instructions: str, text: str, allowed: list[str], client: httpx.Client | None = None) -> dict:
    """One Decisions call. Returns pred/p/top, input tokens, the call's ms and the backoff ms."""
    url, headers, _ = target()
    body = request_body(model, instructions, text, allowed)
    own = client is None
    client = client or httpx.Client(timeout=60)
    backoff, delay, last = 0.0, 2.0, None
    try:
        for _ in range(8):
            t0 = time.perf_counter()
            try:
                r = client.post(url, json=body, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
            else:
                ms = (time.perf_counter() - t0) * 1000
                if r.status_code not in _RETRY:
                    if r.status_code >= 400:
                        raise RuntimeError(f"{model}: HTTP {r.status_code}: {r.text[:300]}")
                    data = r.json()
                    answers = data.get("answers") or []
                    if not answers:
                        raise RuntimeError(f"{model}: no answers in {str(data)[:300]}")
                    u = data.get("usage") or {}
                    tin = u.get("input_tokens") or u.get("prompt_tokens")
                    return {**parse(answers[0], allowed), "in": int(tin) if tin is not None else estimate_tokens(body),
                            "out": 0, "tokens_estimated": tin is None, "ms": round(ms, 1), "llm_ms": round(ms, 1),
                            "backoff_ms": round(backoff)}
                last = RuntimeError(f"HTTP {r.status_code}")
            time.sleep(delay)
            backoff += delay * 1000
            delay = min(delay * 2, 30)
        raise RuntimeError(f"{model}: transient errors exhausted: {last}")
    finally:
        if own:
            client.close()
