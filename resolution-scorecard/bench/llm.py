"""LLM agent baseline (Azure gpt-5-mini): one structured call resolves a ticket
into {intent, target_service, location, kb_article}. Measures tokens + latency
(latency excludes backoff sleeps). This is the GENEROUS baseline — a single call,
where a real tool-calling agent would chain several round-trips and cost more.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from openai import (APIConnectionError, APITimeoutError, AzureOpenAI, BadRequestError,
                    InternalServerError, RateLimitError)

from bench import config

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

_SYSTEM = (
    "You are a telco support resolution agent. Read one customer message and resolve it. "
    "Choose the intent and fill ONLY the parameter that intent needs; leave the others null.\n"
    f"intents: {config.INTENTS}\n"
    "cancel_service & refund -> target_service from "
    f"{config.SERVICES}\n"
    f"check_outage & find_shop -> location from {config.CITIES}\n"
    f"repair_help -> kb_article from {config.KB_ARTICLES}\n"
    "check_balance -> no parameter."
)

_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "resolution", "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "target_service": {"type": ["string", "null"]},
                "location": {"type": ["string", "null"]},
                "kb_article": {"type": ["string", "null"]},
            },
            "required": ["intent", "target_service", "location", "kb_article"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class LLMResult:
    fields: dict
    input_tokens: int
    output_tokens: int
    latency_ms: float


class LLMAgent:
    def __init__(self) -> None:
        c = config.load_llm_config()
        self._deployment = c.deployment
        self._client = AzureOpenAI(azure_endpoint=c.endpoint, api_key=c.api_key, api_version=c.api_version)
        self._extra = None

    def _param_sets(self):
        return [{"max_completion_tokens": 1500, "reasoning_effort": "low"},
                {"max_completion_tokens": 1500}, {"max_tokens": 600, "temperature": 0}, {}]

    def _create(self, base, extra):
        delay = 2.0
        for _ in range(8):
            try:
                t0 = time.perf_counter()
                resp = self._client.chat.completions.create(**base, **extra)
                return resp, (time.perf_counter() - t0) * 1000
            except _RETRYABLE:
                time.sleep(min(delay, 60.0)); delay *= 2
        raise RuntimeError("transient errors exhausted")

    def resolve(self, text: str) -> LLMResult:
        base = dict(model=self._deployment, response_format=_FORMAT,
                    messages=[{"role": "system", "content": _SYSTEM},
                              {"role": "user", "content": f"Customer message:\n{text}"}])
        sets = [self._extra] if self._extra is not None else self._param_sets()
        last = None
        for extra in sets:
            try:
                resp, ms = self._create(base, extra)
            except BadRequestError as e:
                last = e; continue
            self._extra = extra
            data = json.loads(resp.choices[0].message.content or "{}")
            u = resp.usage
            return LLMResult(fields=data, input_tokens=int(u.prompt_tokens),
                             output_tokens=int(u.completion_tokens), latency_ms=ms)
        raise RuntimeError(f"all param sets rejected: {last}")
