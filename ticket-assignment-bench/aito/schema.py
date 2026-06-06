"""Aito schema for `assignments`.

Columns are what a ticket system actually holds at assignment time: the free
text, the structured context (customer, project, priority), and the resolved
assignee. Crucially there is NO product_area column — the area is the latent the
text implies, and is exactly what naive text-similarity leans on while ignoring
the structured customer/project that actually determine the assignee.
"""

from __future__ import annotations

from bench import config

ASSIGNMENTS_SCHEMA = {
    "type": "table",
    "columns": {
        "ticket_id": {"type": "String"},
        "text": {"type": "Text", "analyzer": "english"},
        "customer": {"type": "String"},
        "project": {"type": "String"},
        "priority": {"type": "String"},
        "source": {"type": "String"},
        "sender_domain": {"type": "String"},
        "assignee": {"type": "String"},
    },
}

TABLE_NAME = config.AITO_TABLE


def row_for_upload(t: dict) -> dict:
    return {
        "ticket_id": t["id"],
        "text": t["text"],
        "customer": t["customer"],
        "project": t["project"],
        "priority": t["priority"],
        "source": t["source"],
        "sender_domain": t["sender_domain"],
        "assignee": t["assignee"],
    }
