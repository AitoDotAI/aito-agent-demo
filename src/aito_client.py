"""Thin Aito REST client.

Slim version of the framework's `aito_client.py` — covers the surface
most demos actually use:

  - check_connectivity()  — for /api/health
  - get_schema()          — for /api/schema and the AitoPanel "verify yourself" link
  - predict()             — categorical prediction with $why explanations
  - match()               — similarity search
  - search()              — full-text + filter

For richer patterns (relate, batch predict, per-tenant routing, two-layer
disk cache, semaphores for concurrency control, public-demo cold-start
tracking), lift from `aito-accounting-demo/src/aito_client.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.config import Config


class AitoError(Exception):
    """All errors from this client subclass AitoError.

    Routes that want to surface them as HTTP errors should catch this and
    return an error envelope — e.g.:

        try:
            r = client.predict(...)
        except AitoError as e:
            raise HTTPException(status_code=502, detail=str(e))
    """

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class AitoCall:
    """Lightweight record of a single Aito call. Useful for the
    AitoPanel's latency display and for logging.
    """
    op: str       # "_predict" / "_match" / "_search" / "schema"
    ms: float
    status: int


class AitoClient:
    """Synchronous Aito client. One instance per process; thread-safe via httpx."""

    def __init__(self, config: Config) -> None:
        self._url = config.aito_url
        self._headers = {
            "x-api-key": config.aito_key,
            "content-type": "application/json",
        }
        # httpx.Client is thread-safe + pools connections; one for the
        # lifetime of the process beats per-call construction.
        self._http = httpx.Client(
            base_url=self._url,
            headers=self._headers,
            timeout=10.0,
        )
        self.last_call: AitoCall | None = None

    @property
    def base_url(self) -> str:
        return self._url

    def close(self) -> None:
        self._http.close()

    # ── Low-level ──────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: dict | None = None, op: str | None = None) -> dict:
        try:
            r = self._http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise AitoError(f"Aito {path} unreachable: {e}") from e
        self.last_call = AitoCall(op=op or path, ms=r.elapsed.total_seconds() * 1000, status=r.status_code)
        if r.status_code >= 400:
            try:
                body_json = r.json()
            except Exception:
                body_json = None
            raise AitoError(
                f"Aito {path} returned {r.status_code}",
                status_code=r.status_code,
                body=body_json,
            )
        return r.json()

    # ── Convenience methods ────────────────────────────────────────────

    def check_connectivity(self) -> bool:
        """True iff /schema returns 2xx. Used by /api/health."""
        try:
            self.get_schema()
            return True
        except AitoError:
            return False

    def get_schema(self) -> dict:
        """Whole-DB schema. Cheap; safe to call on every request."""
        return self._request("GET", "/api/v1/schema", op="schema")

    def predict(
        self,
        table: str,
        where: dict,
        predict_field: str,
        limit: int = 5,
        select: list[str] | None = None,
    ) -> dict:
        """Categorical prediction. Pass select=["$p","feature","$why"] to get the
        per-prediction explanation alongside the probability."""
        body: dict = {"from": table, "where": where, "predict": predict_field, "limit": limit}
        if select is not None:
            body["select"] = select
        return self._request("POST", "/api/v1/_predict", body, op="_predict")

    def estimate(self, table: str, where: dict, field: str) -> dict:
        """Numeric estimate of `field` from the given context (price/effort/demand)."""
        return self._request("POST", "/api/v1/_estimate",
                             {"from": table, "where": where, "estimate": field}, op="_estimate")

    def recommend(self, table: str, where: dict, field: str, goal: dict, limit: int = 5) -> dict:
        """Rank the values of `field` that most increase the probability of `goal`."""
        return self._request("POST", "/api/v1/_recommend",
                             {"from": table, "where": where, "recommend": field, "goal": goal, "limit": limit},
                             op="_recommend")

    def relate(self, table: str, where: dict, fields: list[str]) -> dict:
        """Statistical relationships ('drivers'): how each value of `fields` is
        over/under-represented under `where`. lift > 1 = a root cause of `where`."""
        return self._request("POST", "/api/v1/_relate",
                             {"from": table, "where": where, "relate": fields}, op="_relate")

    def query(self, table: str, where: dict | None = None, select: list[str] | None = None,
              order_by: str | dict | None = None, limit: int = 5) -> dict:
        """Fetch rows (used for reference examples)."""
        body: dict = {"from": table, "limit": limit}
        if where is not None:
            body["where"] = where
        if select is not None:
            body["select"] = select
        if order_by is not None:
            body["orderBy"] = order_by
        return self._request("POST", "/api/v1/_query", body, op="_query")

    def match(
        self,
        table: str,
        where: dict,
        match_field: str,
        limit: int = 5,
    ) -> dict:
        """Find rows similar to the given where-fields. Returns $score per hit."""
        return self._request(
            "POST",
            "/api/v1/_match",
            {"from": table, "where": where, "match": match_field, "limit": limit},
            op="_match",
        )

    def search(
        self,
        table: str,
        where: dict,
        limit: int = 10,
        order_by: str | dict | None = None,
    ) -> dict:
        """Full-text + filter search. orderBy: '$similarity', a field name, or {field, desc}."""
        body: dict = {"from": table, "where": where, "limit": limit}
        if order_by is not None:
            body["orderBy"] = order_by
        return self._request("POST", "/api/v1/_search", body, op="_search")
