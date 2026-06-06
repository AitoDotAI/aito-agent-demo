"""Aito layer for the scorecard: create table, upload TRAIN, and `_predict` any
of the resolution fields from {text, sender_domain}. Asserts on bad shape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from bench import config

SCHEMA = {
    "type": "table",
    "columns": {
        "ticket_id": {"type": "String"},
        "text": {"type": "Text", "analyzer": "english"},
        "customer": {"type": "String"},
        "sender_domain": {"type": "String"},
        "intent": {"type": "String"},
        "target_service": {"type": "String", "nullable": True},
        "location": {"type": "String", "nullable": True},
        "kb_article": {"type": "String", "nullable": True},
    },
}
TABLE = config.AITO_TABLE


def _row(t: dict) -> dict:
    return {
        "ticket_id": t["id"], "text": t["text"], "customer": t["customer"],
        "sender_domain": t["sender_domain"], "intent": t["intent"],
        "target_service": t["target_service"], "location": t["location"],
        "kb_article": t["kb_article"],
    }


@dataclass
class Pred:
    feature: str | None
    p: float
    latency_ms: float


class AitoClient:
    def __init__(self) -> None:
        self._read = httpx.Client(base_url=config.aito_url(),
                                  headers={"x-api-key": config.aito_read_key(), "content-type": "application/json"},
                                  timeout=30.0)
        self._write = httpx.Client(base_url=config.aito_url(),
                                   headers={"x-api-key": config.aito_write_key(), "content-type": "application/json"},
                                   timeout=60.0)

    def close(self): self._read.close(); self._write.close()
    def __enter__(self): return self
    def __exit__(self, *e): self.close()

    def recreate_and_upload(self, train: list[dict]) -> int:
        sch = self._write.get("/api/v1/schema"); assert sch.status_code < 400, sch.text[:200]
        if TABLE in sch.json().get("schema", {}):
            assert self._write.delete(f"/api/v1/schema/{TABLE}").status_code < 400
        assert self._write.put(f"/api/v1/schema/{TABLE}", json=SCHEMA).status_code < 400
        rows = [_row(t) for t in train]
        r = self._write.post(f"/api/v1/data/{TABLE}/batch", json=rows)
        assert r.status_code < 400, f"upload failed {r.status_code}: {r.text[:200]}"
        return len(rows)

    def predict(self, field: str, where: dict) -> Pred:
        body = {"from": TABLE, "where": where, "predict": field,
                "select": ["$p", "feature"], "limit": config.PREDICT_LIMIT}
        t0 = time.perf_counter()
        r = self._read.post("/api/v1/_predict", json=body)
        latency_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code < 400, f"_predict({field}) {r.status_code}: {r.text[:200]}"
        hits = r.json().get("hits")
        assert isinstance(hits, list) and hits, f"bad shape for {field}: {r.text[:200]}"
        assert "$p" in hits[0], f"hit missing $p: {hits[0]}"
        return Pred(feature=hits[0].get("feature"), p=float(hits[0]["$p"]), latency_ms=latency_ms)
