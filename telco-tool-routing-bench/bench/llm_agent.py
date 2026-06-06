"""The two LLM baselines.

Baseline A (baseline_full): every tool in the catalog goes in the prompt; one
LLM call selects. This is the naive approach the benchmark expects Aito to beat
easily at large N — it is NOT the bar to clear.

Baseline B (baseline_retrieval): embed tool descriptions once with a local
sentence-transformer, take the top-k by cosine for each ticket, put only those k
in the prompt. k is chosen on VAL. This is the competent baseline a good
engineer would actually ship — the real bar.

Neither baseline can abstain: on an ambiguous ticket it still picks a tool. That
is the point.
"""

from __future__ import annotations

import functools

import numpy as np

from bench import config
from bench.decision import Decision
from bench.llm import LLMClient, LLMSelection


# --- Baseline B retrieval index --------------------------------------------
@functools.lru_cache(maxsize=1)
def _embedder():
    # imported lazily so the data/Aito layers don't pull in torch
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(config.EMBED_MODEL)


class ToolIndex:
    """Embeds a tool catalog once; returns top-k tools by cosine to a query."""

    def __init__(self, tools: list[dict]) -> None:
        self.tools = tools
        model = _embedder()
        texts = [f"{t['name']}: {t['description']}" for t in tools]
        embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        self._mat = np.asarray(embs, dtype=np.float32)  # (N, d), L2-normalized

    def topk(self, query: str, k: int) -> list[dict]:
        model = _embedder()
        q = np.asarray(
            model.encode([query], normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )[0]
        sims = self._mat @ q                      # cosine (both normalized)
        idx = np.argsort(-sims)[:k]
        return [self.tools[i] for i in idx]


# --- selection -> Decision --------------------------------------------------
def _decision_from_selection(
    config_name: str, tool_count: int, ticket: dict, tools_in_prompt: list[dict],
    sel: LLMSelection,
) -> Decision:
    catalog_names = {t["name"] for t in tools_in_prompt}
    valid = sel.tool in catalog_names
    rec = {
        "config": config_name, "tool_count": tool_count, "ticket_id": ticket["id"],
        "op": "llm.select_tool", "model": config.load_llm_config().model_name,
        "n_tools_in_prompt": len(tools_in_prompt), "prompt_chars": sel.prompt_chars,
        "input_tokens": sel.input_tokens, "output_tokens": sel.output_tokens,
        "latency_ms": round(sel.latency_ms, 1), "chosen_tool": sel.tool,
        "valid_tool": valid,
    }
    return Decision(
        config_name=config_name, tool_count=tool_count, ticket_id=ticket["id"],
        chosen_tool=sel.tool, escalated=False, routed_desk=None, mode="select",
        llm_calls=1, input_tokens=sel.input_tokens, output_tokens=sel.output_tokens,
        latency_ms=sel.latency_ms, valid_tool=valid, call_records=[rec],
    )


def resolve_baseline_full(client: LLMClient, ticket: dict, tools: list[dict]) -> Decision:
    sel = client.select_tool(ticket["text"], tools)
    return _decision_from_selection("baseline_full", len(tools), ticket, tools, sel)


def resolve_baseline_retrieval(
    client: LLMClient, ticket: dict, index: ToolIndex, k: int,
) -> Decision:
    shortlist = index.topk(ticket["text"], k)
    sel = client.select_tool(ticket["text"], shortlist)
    return _decision_from_selection("baseline_retrieval", len(index.tools), ticket, shortlist, sel)
