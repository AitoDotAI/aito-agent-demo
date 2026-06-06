"""Azure OpenAI (gpt-5-mini) tool-selection client used by every LLM step.

One model for every config (both baselines + the Aito assist path), so the
cost/accuracy comparison is not confounded by model choice.

We force JSON output via a json_schema response format but do NOT constrain the
tool name to an enum: a model that names a tool not in the catalog is recorded
as an invalid selection (counts as wrong). That is an honest large-catalog
failure mode, and it sidesteps provider enum-size limits at N=340.

Reasoning-model quirks (no `temperature`, `max_completion_tokens` not
`max_tokens`, optional `reasoning_effort`) are handled defensively: the first
call probes which params the deployment accepts and the working set is reused.
"""

from __future__ import annotations

import json
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

from bench import config

# the deployment is rate-limited (TPM/RPM); retry transient errors with backoff
_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
_MAX_RETRIES = 8
_BACKOFF_CAP_S = 60.0

_SYSTEM = (
    "You are a tool-routing agent for a telco (MVNO) support desk. "
    "Given one customer ticket, choose the single best backend tool to resolve it "
    "from the provided catalog. Choose the tool that actually fixes the request, "
    "not one that merely shares a keyword. Respond only with the exact tool name."
)

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "tool_choice",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"tool": {"type": "string"}},
            "required": ["tool"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class LLMSelection:
    tool: str                      # raw model choice (may be out-of-catalog)
    input_tokens: int
    output_tokens: int
    latency_ms: float
    prompt_chars: int


class LLMClient:
    def __init__(self) -> None:
        cfg = config.load_llm_config()
        self._deployment = cfg.deployment
        self._client = AzureOpenAI(
            azure_endpoint=cfg.endpoint,
            api_key=cfg.api_key,
            api_version=cfg.api_version,
        )
        # working extra-kwargs, discovered on first successful call
        self._extra: dict | None = None

    @staticmethod
    def _prompt(text: str, tools: list[dict]) -> str:
        lines = [f"- {t['name']}: {t['description']}" for t in tools]
        catalog = "\n".join(lines)
        return (
            f"Customer ticket:\n{text}\n\n"
            f"Available tools ({len(tools)}):\n{catalog}\n\n"
            f'Return JSON: {{"tool": "<exact tool name from the catalog>"}}'
        )

    def _candidate_param_sets(self) -> list[dict]:
        # tried in order until one works; the winner is cached. Kept modest so a
        # single call doesn't reserve a huge slice of the TPM quota.
        return [
            {"max_completion_tokens": 1500, "reasoning_effort": "low"},
            {"max_completion_tokens": 1500},
            {"max_tokens": 800, "temperature": 0},
            {},
        ]

    def _create_with_backoff(self, base: dict, extra: dict):
        """Call the API, retrying transient (429/5xx/timeout) errors with
        exponential backoff. BadRequestError is NOT retried — it signals a bad
        param set and is surfaced to the probe loop.

        Returns (response, call_ms) where call_ms times ONLY the successful API
        round-trip — backoff sleeps are excluded so the latency metric reflects
        the approach, not this deployment's rate-limit quota state."""
        delay = 2.0
        last: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                t0 = time.perf_counter()
                resp = self._client.chat.completions.create(**base, **extra)
                return resp, (time.perf_counter() - t0) * 1000
            except _RETRYABLE as e:
                last = e
                wait = min(delay, _BACKOFF_CAP_S)
                # honour Retry-After when the SDK surfaces it
                ra = getattr(getattr(e, "response", None), "headers", {}) or {}
                try:
                    wait = max(wait, float(ra.get("retry-after", 0)))
                except (TypeError, ValueError):
                    pass
                time.sleep(wait)
                delay *= 2
        raise RuntimeError(f"transient errors exhausted after {_MAX_RETRIES} retries: {last}")

    def select_tool(self, text: str, tools: list[dict]) -> LLMSelection:
        prompt = self._prompt(text, tools)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ]
        base = dict(
            model=self._deployment,
            messages=messages,
            response_format=_RESPONSE_FORMAT,
        )
        param_sets = [self._extra] if self._extra is not None else self._candidate_param_sets()
        last_bad: Exception | None = None
        for extra in param_sets:
            try:
                resp, latency_ms = self._create_with_backoff(base, extra)
            except BadRequestError as e:   # this param set is unsupported — try next
                last_bad = e
                continue
            self._extra = extra  # cache the working param set
            content = resp.choices[0].message.content or ""
            try:
                tool = json.loads(content)["tool"]
            except (json.JSONDecodeError, KeyError) as e:
                raise AssertionError(
                    f"LLM returned unparseable selection (content={content!r}, "
                    f"finish_reason={resp.choices[0].finish_reason})"
                ) from e
            usage = resp.usage
            return LLMSelection(
                tool=str(tool),
                input_tokens=int(usage.prompt_tokens),
                output_tokens=int(usage.completion_tokens),
                latency_ms=latency_ms,
                prompt_chars=len(prompt),
            )
        raise RuntimeError(f"All Azure OpenAI param sets rejected. Last BadRequest: {last_bad}")
