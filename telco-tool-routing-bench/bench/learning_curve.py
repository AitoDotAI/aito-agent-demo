"""Aito-only data-scaling learning curve — NO LLM calls.

Tests the hypothesis "more history -> Aito works better" directly: upload nested
stratified subsets of TRAIN, and on the fixed TEST split measure how Aito's raw
tool prediction improves with training size — top-1 accuracy, calibration (ECE),
and the auto-fire coverage/precision at the chosen gate.

Because this only calls `_predict` (fast, free of the rate-limited LLM), the
whole curve runs in ~a minute. Restores the full TRAIN upload at the end so the
Aito table is left in the delivered state.

    python -m bench.learning_curve            # default fractions
    python -m bench.learning_curve 0.1 0.25 0.5 1.0
"""

from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from aito.predict import AitoPredictor  # noqa: E402
from aito.upload import _client, create_table, upload_rows  # noqa: E402
from bench import config  # noqa: E402

DEFAULT_FRACS = [0.15, 0.35, 0.6, 1.0]


def _label(t: dict) -> str:
    return t["correct_tool"] or f"desk:{t['escalation_target']}"


def _stratified_prefix(train: list[dict], frac: float) -> list[dict]:
    """Nested stratified subset: same seeded order, take a frac-prefix per label."""
    import random
    rng = random.Random(config.SPLIT_SEED ^ 0xC0FFEE)
    by_label: dict[str, list[dict]] = {}
    for t in train:
        by_label.setdefault(_label(t), []).append(t)
    out: list[dict] = []
    for label in sorted(by_label):
        group = sorted(by_label[label], key=lambda r: r["id"])
        rng.shuffle(group)
        k = max(1, round(len(group) * frac))
        out += group[:k]
    return out


def _ece(points: list[tuple[float, bool]], n_bins: int = 10) -> float:
    n = len(points)
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        inb = [(p, ok) for p, ok in points if lo <= p < hi or (b == n_bins - 1 and p == 1.0)]
        if not inb:
            continue
        conf = sum(p for p, _ in inb) / len(inb)
        acc = sum(1 for _, ok in inb if ok) / len(inb)
        ece += len(inb) / n * abs(acc - conf)
    return ece


def measure(test: list[dict], gate: float) -> dict:
    answerable = [t for t in test if t["correct_tool"]]
    with AitoPredictor() as pred:
        preds = [(t, pred.predict_tool(t["text"]).top) for t in test]
    top1 = sum(1 for t, top in preds if t["correct_tool"] and top.feature == t["correct_tool"])
    cal_pts = [(top.p, top.feature == t["correct_tool"]) for t, top in preds]
    fired = [(t, top) for t, top in preds if top.p >= gate]
    fired_correct = sum(1 for t, top in fired if top.feature == t["correct_tool"])
    return {
        "top1_acc": top1 / len(answerable),
        "ece": _ece(cal_pts),
        "autofire_coverage": len(fired) / len(test),
        "autofire_precision": (fired_correct / len(fired)) if fired else 0.0,
    }


def main() -> None:
    fracs = [float(x) for x in sys.argv[1:]] or DEFAULT_FRACS
    train = json.loads((config.DATA_DIR / "train.json").read_text())
    test = json.loads((config.DATA_DIR / "test.json").read_text())
    gate = json.loads(config.CHOSEN_PARAMS.read_text())["gate"]
    print(f"learning curve over TRAIN fractions {fracs} (gate={gate}), TEST n={len(test)}")

    rows = []
    with _client() as http:
        for frac in fracs:
            subset = _stratified_prefix(train, frac)
            create_table(http, recreate=True)
            n = upload_rows(http, subset)
            m = measure(test, gate)
            m["n_train"] = n
            rows.append(m)
            print(f"  train={n:>4}: top1_acc={m['top1_acc']:.3f}  ECE={m['ece']:.3f}  "
                  f"autofire cov={m['autofire_coverage']:.2f} prec={m['autofire_precision']:.3f}")
        # restore full TRAIN so the table is left as delivered
        create_table(http, recreate=True)
        restored = upload_rows(http, train)
        print(f"restored full TRAIN ({restored} rows)")

    out_path = config.RESULTS_DIR / "learning_curve.json"
    out_path.write_text(json.dumps(rows, indent=2))
    _plot(rows, config.RESULTS_DIR / "learning_curve.png")
    print(f"wrote {out_path.name} and learning_curve.png")


def _plot(rows: list[dict], path) -> None:
    xs = [r["n_train"] for r in rows]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    ax1.plot(xs, [r["top1_acc"] for r in rows], "-o", color="#16c2b9", label="top-1 tool accuracy")
    ax1.plot(xs, [r["autofire_precision"] for r in rows], "-o", color="#1f6f4a", label="auto-fire precision")
    ax1.plot(xs, [r["autofire_coverage"] for r in rows], "-o", color="#9B69FF", label="auto-fire coverage")
    ax1.set_xlabel("TRAIN rows in Aito"); ax1.set_ylabel("rate"); ax1.set_ylim(0, 1)
    ax1.set_title("Aito prediction quality vs training size"); ax1.legend(fontsize=8)
    ax2.plot(xs, [r["ece"] for r in rows], "-o", color="#c2410c")
    ax2.set_xlabel("TRAIN rows in Aito"); ax2.set_ylabel("ECE (lower = better calibrated)")
    ax2.set_title("Calibration error vs training size")
    fig.suptitle("More history → better, better-calibrated Aito predictions (no LLM involved)")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
