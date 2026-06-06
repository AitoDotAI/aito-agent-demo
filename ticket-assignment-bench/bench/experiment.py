"""v3 data-scaling experiment (LLM-free): customer is LATENT and must be inferred.

The real signal is the email `sender_domain` (usually, not always, the customer's
corporate domain). The question: can Aito infer the assignee directly from
{text, sender_domain} and collapse the brittle infer-customer-then-assignee chain?

Methods (all predict the assignee):
  - naive          : majority assignee of the k text-nearest tickets. Ignores sender.
  - cascade        : infer customer via text-NN (majority customer of neighbours),
                     then assignee within that customer. *The broken pipeline.*
  - sender_chain   : parse customer from the sender domain (corporate domains only),
                     filter to that customer, then assignee; fall back to naive when
                     the domain is generic (freemail/portal/automation). *The engineered fix.*
  - aito           : `_predict assignee where {text, sender_domain}` — one query.

Also reports CUSTOMER-inference accuracy (text-NN vs Aito-from-sender) — the step
the chain was trying to recover.

    python -m bench.experiment            # default sizes
    python -m bench.experiment 250 1000 4000
"""

from __future__ import annotations

import functools
import json
import sys
from collections import defaultdict

import numpy as np

from aito.client import AitoClient
from bench import config
from data.org import CUSTOMER_DOMAINS, DOMAIN_TO_CUSTOMER


@functools.lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBED_MODEL)


def _encode(texts: list[str]) -> np.ndarray:
    return np.asarray(_embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False),
                      dtype=np.float32)


def _wmaj(idxs, sims_row, values) -> str:
    score = defaultdict(float)
    for j in idxs:
        score[values[j]] += float(sims_row[j])
    return max(score, key=score.get)


def _ece(points, n_bins=10) -> float:
    n = len(points)
    if not n:
        return 0.0
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        inb = [(p, ok) for p, ok in points if lo <= p < hi or (b == n_bins - 1 and p == 1.0)]
        if inb:
            conf = sum(p for p, _ in inb) / len(inb)
            acc = sum(1 for _, ok in inb if ok) / len(inb)
            ece += len(inb) / n * abs(acc - conf)
    return ece


def run_size(aito: AitoClient, subset: list[dict], test: list[dict],
             test_emb: np.ndarray, k: int, gate: float) -> dict:
    aito.recreate_table()
    n_up = aito.upload(subset)

    tr_emb = _encode([t["text"] for t in subset])
    tr_assignee = [t["assignee"] for t in subset]
    tr_customer = [t["customer"] for t in subset]
    tr_customer_arr = np.array(tr_customer)
    sims = test_emb @ tr_emb.T

    acc = defaultdict(int)            # assignee correct, per method
    cust = defaultdict(int)           # customer inferred correct, per method
    clean_n = clean_acc_aito = generic_n = generic_acc_aito = 0
    cal = []
    fired = fired_ok = 0

    for i, t in enumerate(test):
        gold, gold_cust = t["assignee"], t["customer"]
        reveals = t["sender_domain"] == CUSTOMER_DOMAINS.get(gold_cust)
        top = np.argsort(-sims[i])[:k]

        # naive
        pred_naive = _wmaj(top, sims[i], tr_assignee)
        acc["naive"] += pred_naive == gold

        # cascade: infer customer from text-NN, then assignee within it
        inf_cust = _wmaj(top, sims[i], tr_customer)
        cust["cascade"] += inf_cust == gold_cust
        m = np.where(tr_customer_arr == inf_cust)[0]
        pred_cascade = _wmaj(m[np.argsort(-sims[i][m])][:k], sims[i], tr_assignee) if len(m) else pred_naive
        acc["cascade"] += pred_cascade == gold

        # sender_chain: customer from corporate domain (else fall back to naive)
        sc_cust = DOMAIN_TO_CUSTOMER.get(t["sender_domain"])
        cust["sender"] += sc_cust == gold_cust
        if sc_cust is not None:
            m2 = np.where(tr_customer_arr == sc_cust)[0]
            pred_sender = _wmaj(m2[np.argsort(-sims[i][m2])][:k], sims[i], tr_assignee) if len(m2) else pred_naive
        else:
            pred_sender = pred_naive
        acc["sender"] += pred_sender == gold

        # aito: assignee + customer, both from {text, sender_domain}
        where = {"text": t["text"], "sender_domain": t["sender_domain"]}
        ra = aito.predict("assignee", where)
        rc = aito.predict("customer", where)
        pred_aito, p = ra.top.feature, ra.top.p
        acc["aito"] += pred_aito == gold
        cust["aito"] += rc.top.feature == gold_cust
        cal.append((p, pred_aito == gold))
        if p >= gate:
            fired += 1; fired_ok += pred_aito == gold

        if reveals:
            clean_n += 1; clean_acc_aito += pred_aito == gold
        else:
            generic_n += 1; generic_acc_aito += pred_aito == gold

    n = len(test)
    return {
        "n_train": n_up, "k": k,
        "acc_naive": acc["naive"] / n, "acc_cascade": acc["cascade"] / n,
        "acc_sender": acc["sender"] / n, "acc_aito": acc["aito"] / n,
        "cust_acc_cascade": cust["cascade"] / n, "cust_acc_sender": cust["sender"] / n,
        "cust_acc_aito": cust["aito"] / n,
        "aito_acc_clean_sender": clean_acc_aito / clean_n if clean_n else None,
        "aito_acc_generic_sender": generic_acc_aito / generic_n if generic_n else None,
        "aito_ece": _ece(cal),
        "aito_autoassign_coverage": fired / n,
        "aito_autoassign_precision": fired_ok / fired if fired else 0.0,
    }


def main() -> None:
    sizes = [int(x) for x in sys.argv[1:]] or config.TRAIN_SIZES
    test = json.loads((config.DATA_DIR / "test.json").read_text())
    pool = json.loads((config.DATA_DIR / "pool_train.json").read_text())
    test_emb = _encode([t["text"] for t in test])
    print(f"TEST n={len(test)} | sizes={sizes} | k={config.RETRIEVAL_K} | gate={config.GATE}")

    rows = []
    with AitoClient() as aito:
        for size in sizes:
            m = run_size(aito, pool[:size], test, test_emb, config.RETRIEVAL_K, config.GATE)
            rows.append(m)
            print(f"  train={m['n_train']:>4}: ASSIGNEE naive={m['acc_naive']:.3f} cascade={m['acc_cascade']:.3f} "
                  f"sender={m['acc_sender']:.3f} aito={m['acc_aito']:.3f} | "
                  f"CUSTOMER cascade={m['cust_acc_cascade']:.3f} sender={m['cust_acc_sender']:.3f} aito={m['cust_acc_aito']:.3f}")

    (config.RESULTS_DIR / "scaling.json").write_text(json.dumps(rows, indent=2))
    _plot(rows, config.RESULTS_DIR / "scaling.png")
    print("wrote scaling.json, scaling.png")


def _plot(rows, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    xs = [r["n_train"] for r in rows]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    ax1.plot(xs, [r["acc_naive"] for r in rows], "-o", color="#c2410c", label="naive (text-NN)")
    ax1.plot(xs, [r["acc_cascade"] for r in rows], "-o", color="#9B69FF", label="cascade: text→customer→assignee (the bug)")
    ax1.plot(xs, [r["acc_sender"] for r in rows], "-o", color="#e0b34d", label="engineered: sender→customer→assignee")
    ax1.plot(xs, [r["acc_aito"] for r in rows], "-o", color="#16c2b9", label="Aito: _predict assignee where {text, sender}")
    ax1.set_xlabel("TRAIN tickets"); ax1.set_ylabel("assignee accuracy"); ax1.set_ylim(0, 1)
    ax1.set_xscale("log"); ax1.set_xticks(xs); ax1.set_xticklabels(xs)
    ax1.set_title("Assignee — customer is latent, must be inferred"); ax1.legend(fontsize=8)
    ax2.plot(xs, [r["cust_acc_cascade"] for r in rows], "-o", color="#9B69FF", label="text-NN (what the pipeline did)")
    ax2.plot(xs, [r["cust_acc_sender"] for r in rows], "-o", color="#e0b34d", label="sender-domain lookup")
    ax2.plot(xs, [r["cust_acc_aito"] for r in rows], "-o", color="#16c2b9", label="Aito _predict customer where {text, sender}")
    ax2.set_xlabel("TRAIN tickets"); ax2.set_ylabel("customer-inference accuracy"); ax2.set_ylim(0, 1)
    ax2.set_xscale("log"); ax2.set_xticks(xs); ax2.set_xticklabels(xs)
    ax2.set_title("Inferring the customer: text-similarity vs the sender signal"); ax2.legend(fontsize=8)
    fig.suptitle("v3: the assignee is inferable directly from {text, sender} with Aito — no customer-inference chain")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
