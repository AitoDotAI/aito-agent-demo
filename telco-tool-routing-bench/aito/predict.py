"""Thin wrapper over Aito _predict for `tool` and `escalation_target`.

Pinned request shape (TASK.md). We read the top hit's `$p` straight from the
API and DO NOT transform or recalibrate it — the calibration metric measures
Aito's raw confidence. If the response shape is unexpected, we assert; we never
coerce a malformed response into a plausible-looking number.

Returns a small dataclass per call carrying the measured latency, so the runner
can record real wall-clock without re-timing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from bench import config


@dataclass
class Candidate:
    feature: str | None
    p: float


@dataclass
class PredictResult:
    candidates: list[Candidate]      # ranked, top-first
    latency_ms: float
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def top(self) -> Candidate:
        assert self.candidates, "empty prediction"
        return self.candidates[0]


class AitoPredictor:
    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=config.aito_url(),
            headers={"x-api-key": config.aito_read_key(), "content-type": "application/json"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AitoPredictor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _predict(self, text: str, field_name: str) -> PredictResult:
        body = {
            "from": config.AITO_TABLE,
            "where": {"text": text},
            "predict": field_name,
            "select": ["$p", "feature", "$why"],
            "limit": config.PREDICT_LIMIT,
        }
        t0 = time.perf_counter()
        r = self._http.post("/api/v1/_predict", json=body)
        latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code >= 400:
            raise AssertionError(
                f"Aito _predict({field_name}) returned {r.status_code}: {r.text[:300]}"
            )
        data = r.json()
        assert "hits" in data and isinstance(data["hits"], list), (
            f"unexpected _predict shape (no hits list): {str(data)[:300]}"
        )
        cands: list[Candidate] = []
        for h in data["hits"]:
            assert "$p" in h, f"hit missing $p: {h}"
            cands.append(Candidate(feature=h.get("feature"), p=float(h["$p"])))
        assert cands, f"_predict({field_name}) returned no hits for: {text[:80]!r}"
        return PredictResult(candidates=cands, latency_ms=latency_ms, raw=data)

    def predict_tool(self, text: str) -> PredictResult:
        return self._predict(text, "tool")

    def predict_escalation(self, text: str) -> PredictResult:
        return self._predict(text, "escalation_target")


if __name__ == "__main__":
    # smoke test against a few VAL tickets
    import json
    val = json.loads((config.DATA_DIR / "val.json").read_text())
    with AitoPredictor() as p:
        for t in val[:5]:
            r = p.predict_tool(t["text"])
            print(f"{t['id']} [{t['difficulty']:>9}] gold={t['correct_tool'] or t['escalation_target']:>16} "
                  f"-> {r.top.feature!s:>16} p={r.top.p:.3f}  ({r.latency_ms:.0f}ms)")
