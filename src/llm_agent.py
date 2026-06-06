"""Live LLM-agent baseline for the resolution demo.

Resolves a ticket into {intent, target_service, location, kb_article} with one
structured Azure OpenAI (gpt-5-mini) call — so the UI can show the *real*
response-rate gap next to Aito's instant `_predict`. Measures latency (excluding
backoff sleeps) and tokens; prices the call.

The agent is created lazily on first use, so the app still boots without an
OpenAI key (the /api/resolve-llm route just 503s).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APITimeoutError,
    AzureOpenAI,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

INTENTS = ["cancel_service", "refund", "check_outage", "find_shop", "repair_help", "check_balance"]
SERVICES = ["broadband", "mobile_plan", "tv_package", "landline", "roaming_addon", "cloud_storage"]
CITIES = ["Helsinki", "Espoo", "Tampere", "Turku", "Oulu", "Vantaa", "Jyvaskyla", "Lahti"]
KB = ["cracked_screen", "battery_drain", "water_damage", "wont_charge", "no_signal", "software_update"]

# gpt-5-mini published list rates (USD per 1M tokens). The rate used is returned
# to the UI so the cost figure is traceable.
PRICE_IN = 0.25
PRICE_OUT = 2.00

_SYSTEM = (
    "You are a telco support resolution agent. Read one customer message and resolve it. "
    "Choose the intent and fill ONLY the parameter that intent needs; leave the others null.\n"
    f"intents: {INTENTS}\n"
    f"cancel_service & refund -> target_service from {SERVICES}\n"
    f"check_outage & find_shop -> location from {CITIES}\n"
    f"repair_help -> kb_article from {KB}\n"
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
class LLMResolution:
    intent: str
    fields: dict
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model: str


class LLMAgent:
    def __init__(self) -> None:
        endpoint = os.environ.get("OPENAI_MODEL_URL")
        key = os.environ.get("OPENAI_MODEL_API_KEY")
        if not endpoint or not key:
            raise RuntimeError("OPENAI_MODEL_URL / OPENAI_MODEL_API_KEY not set")
        self.model = os.environ.get("OPENAI_MODEL_NAME", "gpt-5-mini")
        self._deployment = os.environ.get("OPENAI_MODEL_DEPLOYMENT", "gpt-5-mini")
        self._client = AzureOpenAI(
            azure_endpoint=endpoint.rstrip("/"),
            api_key=key,
            api_version=os.environ.get("OPENAI_MODEL_API_VERSION", "2024-08-01-preview"),
        )
        self._extra: dict | None = None

    def _param_sets(self):
        return [
            {"max_completion_tokens": 1500, "reasoning_effort": "low"},
            {"max_completion_tokens": 1500},
            {"max_tokens": 600, "temperature": 0},
            {},
        ]

    def _create(self, base: dict, extra: dict):
        delay = 1.5
        for _ in range(5):
            try:
                t0 = time.perf_counter()
                resp = self._client.chat.completions.create(**base, **extra)
                return resp, (time.perf_counter() - t0) * 1000
            except _RETRYABLE:
                time.sleep(min(delay, 20.0))
                delay *= 2
        raise RuntimeError("transient errors exhausted")

    def resolve(self, text: str) -> LLMResolution:
        base = dict(
            model=self._deployment,
            response_format=_FORMAT,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Customer message:\n{text}"},
            ],
        )
        sets = [self._extra] if self._extra is not None else self._param_sets()
        last = None
        for extra in sets:
            try:
                resp, ms = self._create(base, extra)
            except BadRequestError as e:
                last = e
                continue
            self._extra = extra
            data = json.loads(resp.choices[0].message.content or "{}")
            u = resp.usage
            return LLMResolution(
                intent=str(data.get("intent", "")),
                fields=data,
                input_tokens=int(u.prompt_tokens),
                output_tokens=int(u.completion_tokens),
                latency_ms=ms,
                model=self.model,
            )
        raise RuntimeError(f"all param sets rejected: {last}")


@dataclass
class PickResult:
    tool: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


_TOOL_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "tool_choice", "strict": True,
        "schema": {
            "type": "object",
            "properties": {"tool": {"type": "string"}},
            "required": ["tool"], "additionalProperties": False,
        },
    },
}
_TOOL_SYSTEM = (
    "You are a tool-routing agent for a telco support desk. Given one ticket, choose the single "
    "best backend tool to resolve it from the provided catalog. Pick the tool that actually fixes "
    "the request, not one that merely shares a keyword. Respond with the exact tool name."
)


def _LLMAgent_pick_tool(self, text: str, tools: list[dict]) -> "PickResult":
    catalog = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)
    base = dict(
        model=self._deployment,
        response_format=_TOOL_FORMAT,
        messages=[
            {"role": "system", "content": _TOOL_SYSTEM},
            {"role": "user", "content": f"Ticket:\n{text}\n\nAvailable tools ({len(tools)}):\n{catalog}\n\nReturn JSON: {{\"tool\": \"<exact tool name>\"}}"},
        ],
    )
    sets = [self._extra] if self._extra is not None else self._param_sets()
    last = None
    for extra in sets:
        try:
            resp, ms = self._create(base, extra)
        except BadRequestError as e:
            last = e
            continue
        self._extra = extra
        tool = json.loads(resp.choices[0].message.content or "{}").get("tool", "")
        u = resp.usage
        return PickResult(tool=str(tool), input_tokens=int(u.prompt_tokens),
                          output_tokens=int(u.completion_tokens), latency_ms=ms)
    raise RuntimeError(f"all param sets rejected: {last}")


LLMAgent.pick_tool = _LLMAgent_pick_tool  # type: ignore[attr-defined]


_agent: LLMAgent | None = None


def get_agent() -> LLMAgent:
    global _agent
    if _agent is None:
        _agent = LLMAgent()
    return _agent


def cost_usd(in_tok: int, out_tok: int) -> float:
    return in_tok / 1_000_000 * PRICE_IN + out_tok / 1_000_000 * PRICE_OUT
