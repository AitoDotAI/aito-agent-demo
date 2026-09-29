"""Embed the `support` fixture's texts with a pinned sentence encoder.

Writes `data/support_vectors.json` (tickets and KB articles, for load.py) and
`src/data/support_incoming_vectors.json` (the held-out queue's query vectors,
which ship with the app, since the app does not run a model). The model is
pinned by name AND Hugging Face revision, and the file records the library
versions it was made with. Vectors are rounded to 4 decimals, so a different
CPU or torch build that moves the fifth decimal still yields the same file.

Needs sentence-transformers (the telco bench venv has it):

    telco-tool-routing-bench/run-py scripts/support_fixture/embed.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate import INCOMING, OUT  # noqa: E402

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DIMENSIONS = 384
DECIMALS = 4
VECTORS = OUT / "support_vectors.json"
INCOMING_VECTORS = INCOMING.with_name("support_incoming_vectors.json")


def kb_text(a: dict) -> str:
    return f"{a['title']}. {a['body']}"


def main() -> None:
    import sentence_transformers
    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL, revision=REVISION)
    enc = lambda texts: [[round(float(x), DECIMALS) for x in v]  # noqa: E731
                         for v in model.encode(texts, normalize_embeddings=True, batch_size=256)]
    tickets = json.loads((OUT / "support_tickets.json").read_text())
    kb = json.loads((OUT / "kb_articles.json").read_text())
    held = json.loads(INCOMING.read_text())["tickets"]
    meta = {"model": MODEL, "revision": REVISION, "dimensions": DIMENSIONS, "decimals": DECIMALS,
            "normalized": True, "sentence_transformers": sentence_transformers.__version__,
            "torch": torch.__version__}
    VECTORS.write_text(json.dumps({**meta,
                                   "tickets": dict(zip([t["ticket_id"] for t in tickets], enc([t["text"] for t in tickets]))),
                                   "kb_articles": dict(zip([a["article_id"] for a in kb], enc([kb_text(a) for a in kb])))},
                                  sort_keys=True) + "\n")
    INCOMING_VECTORS.write_text(json.dumps({**meta, "tickets": dict(zip([t["ticket_id"] for t in held],
                                                                         enc([t["text"] for t in held])))},
                                           sort_keys=True) + "\n")
    print(f"{len(tickets)} tickets, {len(kb)} articles -> {VECTORS}; {len(held)} incoming -> {INCOMING_VECTORS}")


if __name__ == "__main__":
    main()
