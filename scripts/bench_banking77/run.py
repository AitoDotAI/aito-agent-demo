"""Run the banking77 benchmark's arms. Resumable: each arm writes one JSON line per
query to results/runs/<arm>.jsonl, and a re-run skips the queries already there.

Arms, for each LLM in --models:
  aito           Aito `_predict intent` from the text alone (no LLM). Also run on
                 the whole test set (aito_full), since it costs no LLM tokens.
  llm_zero       the LLM with the 77 intent labels and the message.
  llm_rag        the LLM with the labels, the message, and the 10 most similar
                 training queries with their intents (embedding retriever, embed.py).
  aito_llm       the LLM with the labels, the message, and Aito's top 5 intents
                 with their $p and the words that drove the top one ($why). The
                 full label list stays allowed, so the LLM can overrule Aito.
The gated arm (Aito when its $p clears a threshold, aito_llm otherwise) needs no
calls of its own: summarize.py derives it, with the threshold chosen on one half
of the sample and scored on the other.

    uv run --with 'aitoai>=1.0' python scripts/bench_banking77/run.py --models gpt-5-mini gpt-5.4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from common import CFG, DATASET, RESULTS, ROOT, jsonl, labels, sample, split

RUNS = RESULTS / "runs"
K_RAG = 10
K_AITO = 5

SYSTEM = (f"You classify one customer message from {CFG['domain']} into exactly one intent from the "
          "allowed list. Answer only JSON: {\"intent\": \"<one allowed label>\"}.")


def uses(arm: str) -> set[str]:
    """Which endpoints an arm's answers come from: aito, aito_full -> Aito; llm_* -> the LLM;
    aito_llm.* -> both."""
    return ({"aito"} if arm.startswith("aito") else set()) | ({"llm"} if "." in arm else set())


def record_endpoints(path, arm: str, here: dict) -> None:
    """Record the endpoints this arm's new answers came from, leaving every other arm's record alone."""
    saved = json.loads(path.read_text()) if path.exists() else {}
    saved.setdefault("per_arm", {})[arm] = {k: here[k] for k in sorted(uses(arm))}
    path.write_text(json.dumps(saved, indent=1) + "\n")


def _aito():
    from load import COLLECTION, client
    import os
    env = os.environ.get("BANKING77_ENV", DATASET).strip()
    _, c = client(None if env.lower() in ("", "master", "env.master") else env)   # the same rule as load.py
    return c, COLLECTION


def _words(why) -> str:
    """The strongest text words behind Aito's top intent, from its $why tree."""
    found: list[tuple[float, str]] = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "relatedPropositionLift":
                # {"text": "refund"}, or a $group of such words: "but + I"
                prop = n.get("proposition", {})
                parts = prop.get("$group", [prop]) if isinstance(prop, dict) else []
                words = [p.get("text") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
                if words:
                    found.append((float(n.get("value", 1.0)), " + ".join(words)))
                return
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(why)
    best = sorted(found, reverse=True)[:4]
    return ", ".join(f"\"{w}\" (x{lift:.1f})" for lift, w in best if lift > 1)


def aito_arm(c, coll, q: dict) -> dict:
    t0 = time.perf_counter()
    r = c.predict(coll, "intent", where={"text": q["text"]}, limit=K_AITO, select=["$p", "feature", "$why"])
    ms = (time.perf_counter() - t0) * 1000
    hits = (r["hits"] if not hasattr(r, "hits") else r.hits) or []
    top = [{"intent": h.get("feature"), "p": round(float(h["$p"]), 4)} for h in hits]
    return {"pred": top[0]["intent"] if top else None, "p": top[0]["p"] if top else None, "top": top,
            "why": _words(hits[0].get("$why")) if hits else "", "ms": round(ms, 1)}


def prompt(q: dict, allowed: list[str], examples: list[dict] | None = None, aito: dict | None = None) -> str:
    lines = ["Allowed intents: " + ", ".join(allowed), ""]
    if examples:
        lines += ["Similar past messages and their intents:"]
        lines += [f'- "{e["text"]}" -> {e["intent"]}' for e in examples] + [""]
    if aito:
        lines.append(f"{CFG['history_owner']} history suggests: " + ", ".join(f"{t['intent']} ({t['p']:.2f})" for t in aito["top"]))
        if aito.get("why"):
            lines.append(f"Words behind the first suggestion: {aito['why']}")
        lines.append("")
    lines.append(f"Message: {q['text']}")
    return "\n".join(lines)


def llm_arm(model: str, q: dict, allowed: list[str], examples=None, aito=None, extra_ms: float = 0.0) -> dict:
    from llm import ask, usd
    r = ask(model, SYSTEM, prompt(q, allowed, examples, aito))
    pred = r["answer"].get("intent")
    return {"pred": pred if pred in allowed else None, "raw": None if pred in allowed else pred, "params": r["params"],
            "in": r["in"], "out": r["out"], "usd": usd(model, r["in"], r["out"]),
            "llm_ms": r["ms"], "backoff_ms": r["backoff_ms"], "ms": round(r["ms"] + extra_ms, 1)}


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import src.config  # noqa: F401  (loads .env: Aito and the LLM endpoint)

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--models", nargs="+", default=["gpt-5-mini"])
    ap.add_argument("--arms", nargs="+", default=["aito_full", "aito", "llm_zero", "llm_rag", "aito_llm"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="only the first N sampled queries (a smoke run)")
    args = ap.parse_args()

    train, test, _ = split()
    allowed = labels(train)
    picked = sample(test)
    if args.limit:
        picked = picked[:args.limit]
    RUNS.mkdir(parents=True, exist_ok=True)
    needs_aito = {"aito_full", "aito", "aito_llm"} & set(args.arms)
    c, coll = _aito() if needs_aito else (None, None)
    # where each arm's answers came from, recorded per arm and only when the arm writes new
    # answers, so resuming someone else's recorded run never relabels their endpoints
    from urllib.parse import urlparse
    llm_url = os.environ.get("OPENAI_MODEL_URL")
    here = {"aito": f"{urlparse(c.api_url).hostname}, Aito v2" if c is not None else None,
            "llm": f"Azure OpenAI, {urlparse(llm_url).hostname}" if llm_url else "OpenAI"}

    def record_endpoints_for(arm: str) -> None:
        with lock:
            record_endpoints(RUNS / "endpoints.json", arm, here)
    if c is not None:
        v = c.get_version()
        meta = RUNS / "engine.json"
        seen = json.loads(meta.read_text()) if meta.exists() else []
        version = v.get("version") if isinstance(v, dict) else str(v)
        if not seen or seen[-1]["version"] != version:
            seen.append({"version": version, "git": v.get("gitRevision") if isinstance(v, dict) else None,
                         "first_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            meta.write_text(json.dumps(seen, indent=1) + "\n")
    lock = threading.Lock()

    def run(name: str, queries: list[dict], fn, workers: int):
        path = RUNS / f"{name}.jsonl"
        done = jsonl(path)
        todo = [q for q in queries if q["qid"] not in done]
        print(f"{name}: {len(done)} done, {len(todo)} to go")
        if todo:
            record_endpoints_for(name)

        def one(q):
            try:
                out = {"qid": q["qid"], "gold": q["intent"], **fn(q)}
            except Exception as e:  # noqa: BLE001  (recorded, and retried on the next run)
                print(f"  {name} {q['qid']}: {e}")
                return
            with lock, path.open("a") as f:
                f.write(json.dumps(out) + "\n")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, todo))

    # Aito first, one call at a time, so its latency is not measured under our own load
    if "aito_full" in args.arms:
        run("aito_full", test if not args.limit else picked, lambda q: aito_arm(c, coll, q), 1)
    if "aito" in args.arms or "aito_llm" in args.arms:
        full = jsonl(RUNS / "aito_full.jsonl")
        run("aito", picked, lambda q: {k: v for k, v in full[q["qid"]].items() if k not in ("qid", "gold")}
            if q["qid"] in full else aito_arm(c, coll, q), 1)
    aito_rows = jsonl(RUNS / "aito.jsonl")

    index = None
    if "llm_rag" in args.arms:
        from embed import DIMENSIONS, EMBED_MODEL, load_index, nearest
        from llm import embed
        index = load_index()

    for model in args.models:
        tag = model.replace("/", "_")
        if "llm_zero" in args.arms:
            run(f"llm_zero.{tag}", picked, lambda q: llm_arm(model, q, allowed), args.workers)
        if "llm_rag" in args.arms:
            def rag(q):
                vec, _, embed_ms = embed(EMBED_MODEL, [q["text"]], DIMENSIONS)
                rows, vectors = index
                t0 = time.perf_counter()
                examples = [rows[i] for i in nearest(vec[0], vectors, K_RAG)]
                search_ms = (time.perf_counter() - t0) * 1000
                out = llm_arm(model, q, allowed, examples=examples, extra_ms=embed_ms)
                return {**out, "embed_ms": round(embed_ms, 1), "search_ms_pure_python": round(search_ms, 1),
                        "examples_hit": sum(e["intent"] == q["intent"] for e in examples)}
            run(f"llm_rag.{tag}", picked, rag, args.workers)
        if "aito_llm" in args.arms:
            run(f"aito_llm.{tag}", picked,
                lambda q: {**llm_arm(model, q, allowed, aito=aito_rows[q["qid"]], extra_ms=aito_rows[q["qid"]]["ms"]),
                           "aito_ms": aito_rows[q["qid"]]["ms"]}, args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
