"""Per-ticket decision record shared by all three configs and consumed by metrics."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Decision:
    config_name: str            # baseline_full | baseline_retrieval | aito
    tool_count: int
    ticket_id: str

    chosen_tool: str | None     # tool fired/selected; None if escalated
    escalated: bool
    routed_desk: str | None     # desk if escalated, else None
    mode: str                   # select | auto | assist | escalate

    llm_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: float

    # baseline-only diagnostics
    valid_tool: bool = True     # was chosen_tool actually in the catalog?

    # aito-only diagnostics (recorded for EVERY aito ticket, even when escalated,
    # so calibration can bin the raw tool-prediction confidence)
    aito_top_p: float | None = None
    aito_tool_pred: str | None = None

    # per-call records to append to calls.jsonl (filled by the agent)
    call_records: list[dict] = field(default_factory=list)
