"""Aito table schema for `tickets`.

DELIBERATE DEVIATION FROM TASK.md's pinned schema, documented here and in
REPORT.md: TASK pins `tool` as a non-nullable String, but ambiguous tickets
have no correct tool (correct_tool=null) — their right action is to escalate.
We make `tool` nullable so ambiguous TRAIN rows carry a *null* tool. This is
load-bearing for the calibration claim:

  - With null tool, ambiguous-like text matches training rows that give no
    single-tool signal, so _predict returns low, spread `$p` -> the gate
    escalates. That is precisely the abstain behaviour the benchmark tests.
  - The rejected alternatives are worse: a sentinel "escalate" tool would be
    learned as a high-confidence class (faking calibrated abstention), and
    dropping ambiguous tickets from TRAIN would leave escalation_target
    prediction with nothing to learn from.

Only TRAIN rows are ever uploaded.
"""

from __future__ import annotations

from bench import config

TICKETS_SCHEMA: dict = {
    "type": "table",
    "columns": {
        "ticket_id": {"type": "String"},
        "text": {"type": "Text", "analyzer": "english"},
        "tool": {"type": "String", "nullable": True},
        "escalation_target": {"type": "String", "nullable": True},
    },
}


def row_for_upload(ticket: dict) -> dict:
    """Map a dataset ticket to an Aito table row. For ambiguous tickets the
    tool is null and the escalation_target carries the label."""
    return {
        "ticket_id": ticket["id"],
        "text": ticket["text"],
        "tool": ticket["correct_tool"],            # None for ambiguous
        "escalation_target": ticket["escalation_target"],  # None for clear/medium
    }


TABLE_NAME = config.AITO_TABLE
