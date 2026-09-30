"""Has the LLM memorised the dataset? A cheap probe for pretraining contamination.

banking77 (2020) and CLINC150 (2019) are public, so they may be in the models'
training data, which would flatter the LLM arms compared with a company's own,
private data. Two probes, no retrieval, no labels given:

1. Label recall: "list the intent labels of <dataset>". Scored as the share of the
   true labels named exactly (case-insensitive), and how many named labels are
   not real ones.
2. Completion: the first half of a held-out test message (by words); the model
   continues it. Scored as the share completed verbatim (normalised), and the
   share whose first three continued words match.

The metrics were fixed before the first run. A high verbatim rate shows
memorisation. A low one doesn't rule it out, since the models may know the data
without reproducing it word for word.

    BENCH_DATASET=clinc150 uv run python scripts/bench_banking77/contamination.py --models gpt-5.4 gpt-5-mini
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime, timezone

from common import CFG, DATASET, RESULTS, ROOT, labels, norm, sample, split

N_COMPLETE = 50
NAMES = {"banking77": "banking77 (PolyAI, 2020)", "clinc150": "CLINC150 / clinc_oos (Larson et al., 2019)"}


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import src.config  # noqa: F401  (loads .env)
    from llm import ask

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--models", nargs="+", default=["gpt-5.4"])
    ap.add_argument("--framing", choices=["named", "neutral"], default="named",
                    help="named: the prompts name the dataset (the models tend to refuse); neutral: they don't")
    args = ap.parse_args()
    train, test, _ = split()
    truth = {l.lower() for l in labels(train)}
    picked = sample(test)
    rng = random.Random(7)
    probes = [q for q in rng.sample(picked, N_COMPLETE)]

    out = {"dataset": CFG["title"], "framing": args.framing, "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "method": __doc__.split("\n\n")[1:4], "models": {}}
    for model in args.models:
        if args.framing == "named":
            ask_labels = (f"List every intent label in the {NAMES[DATASET]} intent classification dataset, exactly "
                          'as the labels are written in the dataset. Reply {"labels": ["...", ...]}.')
        else:
            ask_labels = (f"An intent classifier for {CFG['domain']} uses {len(truth)} snake_case intent labels. "
                          f"Write the {len(truth)} labels you think it uses. Reply {{\"labels\": [\"...\", ...]}}.")
        r = ask(model, "Answer only JSON.", ask_labels)
        named = [str(x).strip().lower() for x in r["answer"].get("labels", []) if str(x).strip()]
        hits = sorted(set(named) & truth)
        recall = {"true_labels": len(truth), "named": len(set(named)), "exact_hits": len(hits),
                  "recall": round(len(hits) / len(truth), 3), "named_not_real": len(set(named) - truth),
                  "tokens": r["in"] + r["out"]}
        completions = []
        for q in probes:
            w = q["text"].split()
            cut = max(1, len(w) // 2)
            head, tail = " ".join(w[:cut]), " ".join(w[cut:])
            if args.framing == "named":
                ask_rest = (f"This message is from the {NAMES[DATASET]} dataset's test split. Continue it exactly "
                            f'as it appears in the dataset.\nStart: "{head}"\nReply {{"rest": "<the rest of the message>"}}')
            else:
                ask_rest = (f"Here is the start of a one-line message from {CFG['domain']}. Write the most likely "
                            f'rest of it.\nStart: "{head}"\nReply {{"rest": "<the rest of the message>"}}')
            c = ask(model, "Answer only JSON.", ask_rest)
            got = str(c["answer"].get("rest", ""))
            refused = bool(re.search(r"can.t|cannot|sorry|copyright", got, re.I)) or not got.strip() or got == "None"
            completions.append({"qid": q["qid"], "head": head, "tail": tail, "got": got, "refused_or_empty": refused,
                                "verbatim": norm(" ".join(words(got))) == norm(" ".join(words(tail))),
                                "first3": words(got)[:3] == words(tail)[:3] and len(words(tail)) > 0})
        out["models"][model] = {
            "label_recall": recall, "label_hits": hits,
            "completion": {"n": len(completions), "refused_or_empty": sum(c["refused_or_empty"] for c in completions),
                           "verbatim": sum(c["verbatim"] for c in completions),
                           "verbatim_share": round(sum(c["verbatim"] for c in completions) / len(completions), 3),
                           "first3_share": round(sum(c["first3"] for c in completions) / len(completions), 3)},
            "completions": completions}
        m = out["models"][model]
        print(f"{model}: labels {recall['exact_hits']}/{recall['true_labels']} exact ({recall['named_not_real']} "
              f"named that aren't real); completions verbatim {m['completion']['verbatim']}/{len(completions)}, "
              f"first 3 words {m['completion']['first3_share']:.0%}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"contamination.{args.framing}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
