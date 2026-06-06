"""Append-only JSONL log of every LLM and Aito call (request, response, latency,
tokens). Acceptance criterion #3: every call is logged.

One CallLog per run; the runner owns it and records each call with full context
(config, tool_count, ticket_id). Keeping logging in one place means the wrappers
stay thin and we get exactly one line per logical call.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from bench import config


class CallLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.CALLS_LOG
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.n = 0

    def record(self, **fields: Any) -> None:
        fields.setdefault("t", time.time())
        self._fh.write(json.dumps(fields, ensure_ascii=False) + "\n")
        self._fh.flush()
        self.n += 1

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "CallLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
