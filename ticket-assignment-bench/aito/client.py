"""Aito client for v2: table create + batch upload (write key) and
`_predict assignee` conditioned on structured fields (read key).

Predicts assignee from whatever `where` fields are supplied — the whole point is
that adding `customer`/`project` to the query is all it takes for Aito to
condition on structure, with no separate retrieval/filter code. Asserts on
unexpected response shape; never coerces.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from aito.schema import ASSIGNMENTS_SCHEMA, TABLE_NAME, row_for_upload
from bench import config


@dataclass
class Candidate:
    feature: str | None
    p: float


@dataclass
class PredictResult:
    candidates: list[Candidate]
    latency_ms: float

    @property
    def top(self) -> Candidate:
        assert self.candidates, "empty prediction"
        return self.candidates[0]


class AitoClient:
    def __init__(self) -> None:
        self._read = httpx.Client(
            base_url=config.aito_url(),
            headers={"x-api-key": config.aito_read_key(), "content-type": "application/json"},
            timeout=30.0,
        )
        self._write = httpx.Client(
            base_url=config.aito_url(),
            headers={"x-api-key": config.aito_write_key(), "content-type": "application/json"},
            timeout=60.0,
        )

    def close(self) -> None:
        self._read.close(); self._write.close()

    def __enter__(self): return self
    def __exit__(self, *e): self.close()

    # --- write ---
    def recreate_table(self) -> None:
        schema = self._write.get("/api/v1/schema")
        assert schema.status_code < 400, schema.text[:200]
        if TABLE_NAME in schema.json().get("schema", {}):
            r = self._write.delete(f"/api/v1/schema/{TABLE_NAME}")
            assert r.status_code < 400, f"drop failed: {r.text[:200]}"
        r = self._write.put(f"/api/v1/schema/{TABLE_NAME}", json=ASSIGNMENTS_SCHEMA)
        assert r.status_code < 400, f"create failed: {r.text[:200]}"

    def upload(self, tickets: list[dict]) -> int:
        rows = [row_for_upload(t) for t in tickets]
        r = self._write.post(f"/api/v1/data/{TABLE_NAME}/batch", json=rows)
        assert r.status_code < 400, f"upload failed {r.status_code}: {r.text[:200]}"
        return len(rows)

    # --- predict ---
    def predict(self, field: str, where: dict) -> PredictResult:
        body = {"from": TABLE_NAME, "where": where, "predict": field,
                "select": ["$p", "feature"], "limit": config.PREDICT_LIMIT}
        t0 = time.perf_counter()
        r = self._read.post("/api/v1/_predict", json=body)
        latency_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code < 400, f"_predict({field}) failed {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "hits" in data and isinstance(data["hits"], list), f"bad shape: {str(data)[:200]}"
        cands = []
        for h in data["hits"]:
            assert "$p" in h, f"hit missing $p: {h}"
            cands.append(Candidate(feature=h.get("feature"), p=float(h["$p"])))
        assert cands, f"no hits for predict({field}) where={where}"
        return PredictResult(candidates=cands, latency_ms=latency_ms)

    def predict_assignee(self, where: dict) -> PredictResult:
        return self.predict("assignee", where)
