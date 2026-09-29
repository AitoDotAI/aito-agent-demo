"""Embed banking77's training queries once, for the LLM + RAG arm's retriever.

The retriever is the usual one: an embedding model and the k nearest training
queries by cosine similarity. The vectors are cached in data/ (not committed);
the model, dimensions and token count are recorded in results/embedding.json.

    uv run python scripts/bench_banking77/embed.py
"""

from __future__ import annotations

import json
import math
import sys

from common import DATA, RESULTS, split

EMBED_MODEL = "text-embedding-3-large"
DIMENSIONS = 256
CACHE = DATA / f"train_{EMBED_MODEL}_{DIMENSIONS}.json"


def unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def load_index() -> tuple[list[dict], list[list[float]]]:
    data = json.loads(CACHE.read_text())
    if (data["model"], data["dimensions"]) != (EMBED_MODEL, DIMENSIONS):
        raise SystemExit(f"{CACHE} was made with another model; run embed.py again")
    train, _, _ = split()
    if len(data["vectors"]) != len(train):
        raise SystemExit(f"{CACHE} has {len(data['vectors'])} vectors for {len(train)} training queries")
    return train, [unit(v) for v in data["vectors"]]


def nearest(q: list[float], vectors: list[list[float]], k: int) -> list[int]:
    q = unit(q)
    scores = [sum(a * b for a, b in zip(q, v)) for v in vectors]
    return sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:k]


def main() -> int:
    sys.path.insert(0, str(DATA.parent.parent.parent))
    import src.config  # noqa: F401  (loads .env for the LLM endpoint, like the rest of the repo)
    from llm import embed

    train, _, _ = split()
    if CACHE.exists():
        print(f"{CACHE.name}: already there")
        return 0
    vectors, tokens = [], 0
    for i in range(0, len(train), 500):
        vs, t, _ = embed(EMBED_MODEL, [r["text"] for r in train[i:i + 500]], DIMENSIONS)
        vectors += vs
        tokens += t
        print(f"  {len(vectors)}/{len(train)}")
    CACHE.write_text(json.dumps({"model": EMBED_MODEL, "dimensions": DIMENSIONS, "vectors": vectors}))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "embedding.json").write_text(json.dumps(
        {"model": EMBED_MODEL, "dimensions": DIMENSIONS, "training_queries": len(train), "tokens": tokens}, indent=1) + "\n")
    print(f"{len(vectors)} vectors, {tokens} tokens -> {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
