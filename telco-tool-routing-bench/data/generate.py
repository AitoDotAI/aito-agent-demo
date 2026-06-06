"""Build deterministic train/val/test splits and write data/{train,val,test}.json.

Stratified by label (the correct_tool for clear/medium, the escalation desk for
ambiguous) so every tool and every desk is proportionally represented in all
three splits — TRAIN must contain examples of every label for Aito to learn it,
and TEST must exercise every label.

Asserts no ticket id appears in two splits. Fully reproducible from the seeds.

    python -m data.generate
"""

from __future__ import annotations

import json
import random

from bench import config
from data.tickets import build_tickets


def _label(row: dict) -> str:
    return row["correct_tool"] if row["correct_tool"] else f"desk:{row['escalation_target']}"


def split_tickets(rows: list[dict]) -> dict[str, list[dict]]:
    rng = random.Random(config.SPLIT_SEED)
    by_label: dict[str, list[dict]] = {}
    for r in rows:
        by_label.setdefault(_label(r), []).append(r)

    out: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    rt, rv = config.SPLIT_RATIOS["train"], config.SPLIT_RATIOS["val"]
    for label in sorted(by_label):
        group = sorted(by_label[label], key=lambda r: r["id"])  # stable before shuffle
        rng.shuffle(group)
        n = len(group)
        n_train = round(n * rt)
        n_val = round(n * rv)
        # guard tiny groups: ensure val/test get at least 1 if the group allows
        n_train = min(n_train, n - 2) if n >= 3 else n_train
        out["train"] += group[:n_train]
        out["val"] += group[n_train:n_train + n_val]
        out["test"] += group[n_train + n_val:]
    return out


def _validate(splits: dict[str, list[dict]], total: int) -> None:
    ids = {name: {r["id"] for r in rows} for name, rows in splits.items()}
    assert ids["train"].isdisjoint(ids["val"]), "train/val id overlap"
    assert ids["train"].isdisjoint(ids["test"]), "train/test id overlap"
    assert ids["val"].isdisjoint(ids["test"]), "val/test id overlap"
    union = ids["train"] | ids["val"] | ids["test"]
    assert len(union) == total, f"splits cover {len(union)} != {total} tickets"
    # every label present in TRAIN (otherwise Aito can't predict it)
    train_labels = {_label(r) for r in splits["train"]}
    all_labels = {_label(r) for rows in splits.values() for r in rows}
    missing = all_labels - train_labels
    assert not missing, f"labels missing from TRAIN: {missing}"


def main() -> None:
    rows = build_tickets()
    splits = split_tickets(rows)
    _validate(splits, len(rows))
    for name, data in splits.items():
        path = config.DATA_DIR / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"wrote {path.relative_to(config.PKG_ROOT)}: {len(data)} tickets")
    # summary
    for name in ("train", "val", "test"):
        from collections import Counter
        diff = Counter(r["difficulty"] for r in splits[name])
        print(f"  {name:>5}: {dict(diff)}")


if __name__ == "__main__":
    main()
