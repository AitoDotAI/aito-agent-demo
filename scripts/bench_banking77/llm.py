"""The LLM side of the benchmark, self-contained so it can be reproduced with your own keys.

Azure OpenAI when OPENAI_MODEL_URL + OPENAI_MODEL_API_KEY are set (the model name
is the deployment name), otherwise OpenAI with OPENAI_API_KEY. Latency is the
successful call's own time: rate-limit backoff is excluded and counted apart.
"""

from __future__ import annotations

import json
import os
import time

from openai import (APIConnectionError, APITimeoutError, AzureOpenAI, BadRequestError, InternalServerError,
                    OpenAI, RateLimitError)

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

#: USD per 1M tokens (input, output) with the source; a model not listed has its tokens
#: reported and no spend, rather than a guessed price
PRICES = {
    "gpt-5-mini": {"in": 0.25, "out": 2.00, "source": "gpt-5-mini list price, as in src/llm_agent.py (PRICE_IN/PRICE_OUT); check it against your provider"},
}
#: per-call settings to try in order, for models that reject some of them
_PARAMS = [{"max_completion_tokens": 1500, "reasoning_effort": "low"}, {"max_completion_tokens": 1500}, {}]
_UNSUPPORTED = __import__("re").compile(r"unsupported|not supported|unrecognized|unknown parameter|"
                                       r"extra inputs are not permitted", __import__("re").I)
_clients: dict = {}
_settled: dict[str, dict] = {}


def _client():
    if "c" not in _clients:
        url, key = os.environ.get("OPENAI_MODEL_URL"), os.environ.get("OPENAI_MODEL_API_KEY")
        if url and key:
            _clients["c"] = AzureOpenAI(azure_endpoint=url.rstrip("/"), api_key=key,
                                        api_version=os.environ.get("OPENAI_MODEL_API_VERSION", "2024-12-01-preview"))
        else:
            _clients["c"] = OpenAI()
    return _clients["c"]


def usd(model: str, i: int, o: int) -> float | None:
    p = PRICES.get(model)
    return None if p is None else i / 1e6 * p["in"] + o / 1e6 * p["out"]


def ask(model: str, system: str, user: str) -> dict:
    """One JSON-mode call. Returns the parsed answer, tokens, the call's ms and the backoff ms."""
    base = {"model": model, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    backoff, last = 0.0, None
    for extra in ([_settled[model]] if model in _settled else _PARAMS):
        delay = 2.0
        for _ in range(8):
            try:
                t0 = time.perf_counter()
                resp = _client().chat.completions.create(**base, **extra)
                ms = (time.perf_counter() - t0) * 1000
                break
            except _RETRYABLE as e:
                last = e
                time.sleep(delay)
                backoff += delay * 1000
                delay = min(delay * 2, 30)
            except BadRequestError as e:
                # only an unsupported setting moves to the next set; anything else (a content filter,
                # a bad prompt) fails this call alone, instead of silently changing every later call
                if not _UNSUPPORTED.search(str(e)):
                    raise
                last, resp = e, None
                break
        else:
            raise RuntimeError(f"{model}: transient errors exhausted: {last}")
        if resp is None:
            continue
        _settled[model] = extra
        try:
            data = json.loads(resp.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            data = {}
        u = resp.usage
        return {"answer": data if isinstance(data, dict) else {}, "params": extra, "in": int(u.prompt_tokens),
                "out": int(u.completion_tokens), "ms": round(ms, 1), "backoff_ms": round(backoff)}
    raise RuntimeError(f"{model}: every parameter set was rejected: {last}")


def embed(model: str, texts: list[str], dimensions: int) -> tuple[list[list[float]], int, float]:
    """Embeddings for a batch; returns the vectors, the tokens and the call's ms."""
    delay = 2.0
    for _ in range(8):
        try:
            t0 = time.perf_counter()
            r = _client().embeddings.create(model=model, input=texts, dimensions=dimensions, encoding_format="float")
            return [d.embedding for d in r.data], int(r.usage.total_tokens), (time.perf_counter() - t0) * 1000
        except _RETRYABLE:
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"{model}: embedding failed after retries")
