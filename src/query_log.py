"""The Aito queries a request sent, for the side panels (docs: aito-erp-demo
docs/design/query-panes.md). AitoClient records each request at its one send path;
a route returns them as `_queries`.

A record holds the op, the API path (no scheme, host or db/env prefix), the env name
and the exact JSON body. Never headers: the API key cannot reach a record.
"""

from __future__ import annotations

import contextvars
import json

#: enough for a pane (the 360 makes ~46 calls); a view that makes more ships only the first ones
MAX_RECORDS = 60

_records: contextvars.ContextVar[list | None] = contextvars.ContextVar("aito_queries", default=None)


def start() -> list:
    """A fresh record list for this request (worker threads that copy the context share it)."""
    lst: list = []
    _records.set(lst)
    return lst


def record(op: str, path: str, env: str | None, body: dict | None, ms: float, status: int) -> None:
    lst = _records.get()
    if lst is None or len(lst) >= MAX_RECORDS:
        return
    lst.append({"op": op, "path": path, "env": env or "master",
                "body": json.loads(json.dumps(body)) if body is not None else None,
                "ms": round(ms, 1), "status": status})


def current() -> list:
    return list(_records.get() or [])
