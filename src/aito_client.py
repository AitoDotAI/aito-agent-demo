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

import os
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
    """Synchronous Aito client. One instance per process; thread-safe via httpx.

    Speaks either REST surface. `config.aito_api_version` picks the path prefix
    (`/api/v1` or `/api/v2`); the v2 contract differences that are pure renames
    are normalised here so callers stay version-agnostic. See `docs/v2-migration.md`
    for the differences that are NOT shimmable.
    """

    def __init__(self, config: Config) -> None:
        self._url = config.aito_url
        self._ver = config.aito_api_version
        self._env = config.aito_env
        self._headers = {
            "x-api-key": config.aito_key,
            "content-type": "application/json",
        }
        # httpx.Client is thread-safe + pools connections; one for the
        # lifetime of the process beats per-call construction.
        # 10s was too tight: the shared instance now answers some v2 calls in
        # ~5s, and under concurrent load that tipped ordinary requests into
        # timeouts surfacing as 502s. Overridable for local experiments.
        self._http = httpx.Client(
            base_url=self._url,
            headers=self._headers,
            timeout=float(os.environ.get("AITO_TIMEOUT_S", "30")),
        )
        self.last_call: AitoCall | None = None

    @property
    def base_url(self) -> str:
        return self._url

    def close(self) -> None:
        self._http.close()

    # ── Low-level ──────────────────────────────────────────────────────

    def _path(self, suffix: str) -> str:
        """`_predict` → `/api/v1/_predict` or `/api/v2/_predict`."""
        return f"/api/{self._ver}/{suffix.lstrip('/')}"

    # v2 renamed the predicted value on _predict/_recommend hits from `feature`
    # to `$value` and dropped `field`. It is a pure rename, so both spellings are
    # published on every hit and callers can read either. NOTE: v2's _match hits
    # were NOT renamed — they still carry field/feature (core gap G3).
    def _normalize_hits(self, payload: dict) -> dict:
        hits = payload.get("hits")
        if not isinstance(hits, list):
            return payload
        for h in hits:
            if not isinstance(h, dict):
                continue
            if "$value" in h and "feature" not in h:
                h["feature"] = h["$value"]
            elif "feature" in h and "$value" not in h:
                h["$value"] = h["feature"]
        return payload

    def _select(self, select: list[str] | None) -> list[str] | None:
        """v2 rejects `feature` in select ("no such field 'feature'"); it spells
        the predicted value `$value`. Translate so call sites keep one spelling."""
        if select is None or self._ver == "v1":
            return select
        return ["$value" if s == "feature" else s for s in select]

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
        return self._normalize_hits(r.json())

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
        return self._request("GET", self._path("schema"), op="schema")

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
            body["select"] = self._select(select)
        return self._request("POST", self._path("_predict"), body, op="_predict")

    def estimate(self, table: str, where: dict, field: str) -> dict:
        """Numeric estimate of `field` from the given context (price/effort/demand).

        Normalised to v1's `{"estimate": <n>, "why": …}` shape. On the v2 STORAGE
        ENGINE (rep2) the same call answers `{"kind":"estimate","data":{"value":…}}`
        and drops `why` entirely — see aito-core#1221. Callers read `.get("estimate")`
        on either; `why` is simply absent on rep2.
        """
        r = self._request("POST", self._path("_estimate"),
                          {"from": table, "where": where, "estimate": field}, op="_estimate")
        if "estimate" not in r and isinstance(r.get("data"), dict):
            r["estimate"] = r["data"].get("value")
        return r

    def recommend(self, table: str, where: dict, field: str, goal: dict, limit: int = 5) -> dict:
        """Rank the values of `field` that most increase the probability of `goal`."""
        return self._request("POST", self._path("_recommend"),
                             {"from": table, "where": where, "recommend": field, "goal": goal, "limit": limit},
                             op="_recommend")

    def relate(self, table: str, where: dict, fields: list[str]) -> dict:
        """Statistical relationships ('drivers'): how each value of `fields` is
        over/under-represented under `where`. lift > 1 = a root cause of `where`."""
        return self._request("POST", self._path("_relate"),
                             {"from": table, "where": where, "relate": fields}, op="_relate")

    def relate_on(self, table: str, target: dict, on: dict) -> dict:
        """Drivers of `target` SCOPED to `on` — relate the outcome (e.g. churned=yes)
        within a population (e.g. size=SMB). Each hit's `condition` is a field-value
        and ps.pOnCondition is the within-population outcome RATE for it."""
        return self._request("POST", self._path("_relate"),
                             {"from": table, "relate": {"$on": [target, on]}}, op="_relate")

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
        return self._request("POST", self._path("_query"), body, op="_query")

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
            self._path("_match"),
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
        return self._request("POST", self._path("_search"), body, op="_search")
