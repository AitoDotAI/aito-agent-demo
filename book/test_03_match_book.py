"""Booktest: Aito as a RAG-augmentation primitive — match the ANSWER, not just
the question.

Classic RAG embeds a question, retrieves the k most similar past questions, and
asks the LLM to synthesise an answer from them. Aito can do BOTH, from one index,
with calibrated confidence:

  - `_match` on the answer field returns the answer directly (here: the KB
    article that resolves the ticket), ranked with `$p` — no LLM synthesis step.
  - `_similarity` returns the nearest past tickets — the retrieval a vector store
    would do — when you do want to hand context to the LLM.

So Aito is the predictive recall layer under an agent platform: it either answers
outright (the confident, routine case) or hands the LLM a tight, grounded
shortlist. Snapshotted via snapshot_httpx so it stays deterministic.

    ./do test-book
    ./do test-book -s -a book/test_03_match_book.py   # re-record against live Aito
"""

import booktest as bt
import httpx

from src.config import load_config

# repair tickets — the KB article is the "answer" to match
QUESTIONS = [
    ("My phone screen is shattered.", "cracked_screen"),
    ("The battery dies within an hour.", "battery_drain"),
    ("I dropped my handset in water.", "water_damage"),
    ("It won't charge when plugged in.", "wont_charge"),
    ("No signal at all on the device.", "no_signal"),
]


@bt.snapshot_httpx()
def test_match_vs_retrieval(t: bt.TestCaseRun):
    cfg = load_config()
    t.h1("Aito: match the answer, not just the question")
    t.tln(f"DB `{cfg.aito_url}` · table `resolutions` (question = `text`, answer = `kb_article`)")
    t.tln("")

    direct_correct = 0
    with httpx.Client(base_url=cfg.aito_url,
                      headers={"x-api-key": cfg.aito_key, "content-type": "application/json"},
                      timeout=15.0) as c:
        for q, gold in QUESTIONS:
            t.h2(q)

            # (1) direct answer — _match the answer field
            m = c.post("/api/v1/_match", json={
                "from": "resolutions", "where": {"text": q}, "match": "kb_article", "limit": 2})
            m.raise_for_status()
            hits = m.json().get("hits", [])
            top = hits[0] if hits else {}
            ok = top.get("feature") == gold
            direct_correct += ok
            t.tln(f"- **direct answer** (`_match kb_article`): **{top.get('feature')}** "
                  f"(p={top.get('$p', 0):.3f}){'' if ok else f'  ✗ expected {gold}'}")

            # (2) retrieval — _similarity over past tickets (what a vector store returns)
            s = c.post("/api/v1/_similarity", json={
                "from": "resolutions", "similarity": {"text": q},
                "select": ["text", "kb_article", "$score"], "limit": 2})
            s.raise_for_status()
            sims = s.json().get("hits", [])
            t.tln("- retrieved neighbours (`_similarity`):")
            for h in sims:
                t.iln(f"    · “{h.get('text')}” → {h.get('kb_article')}")
            t.tln("")

    t.h2("Summary")
    t.tln(f"- direct-answer accuracy (`_match`): {direct_correct}/{len(QUESTIONS)}")
    t.assertln("Aito matches the answer directly on clear questions",
               direct_correct >= len(QUESTIONS) - 1)
