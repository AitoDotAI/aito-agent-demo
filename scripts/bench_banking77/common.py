"""Shared pieces of the intent benchmark (banking77, CLINC150): the pinned data, the pinned sample,
the statistics. Standard library only, so the numbers can be checked without
installing anything."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # the repo

#: the datasets this harness runs on, pinned by content. BENCH_DATASET picks one
#: (banking77 by default); banking77 keeps the top-level data/ and results/ it was
#: published with, any other dataset gets its own subdirectory.
DATASETS = {
    "banking77": {
        "title": "banking77", "license": "CC BY 4.0",
        "source": "PolyAI, https://github.com/PolyAI-LDN/task-specific-datasets",
        "base": "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data",
        "files": {"train.csv": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
                  "test.csv": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"},
        "per_intent": 8,
        "domain": "a bank's support chat", "history_owner": "This bank's",
    },
    "clinc150": {
        "title": "CLINC150 (in-scope)", "license": "CC BY 3.0",
        "source": "Larson et al. 2019, https://github.com/clinc/oos-eval",
        "base": "https://raw.githubusercontent.com/clinc/oos-eval/master/data",
        "files": {"data_full.json": "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0"},
        "per_intent": 4,
        "domain": "a user of a general-purpose virtual assistant", "history_owner": "This assistant's",
    },
}
DATASET = os.environ.get("BENCH_DATASET", "banking77").strip()
if DATASET not in DATASETS:
    raise SystemExit(f"BENCH_DATASET={DATASET!r}: pick one of {sorted(DATASETS)}")
CFG = DATASETS[DATASET]
DATA = HERE / "data" if DATASET == "banking77" else HERE / "data" / DATASET   # downloaded, not committed
RESULTS = (Path(os.environ["BANKING77_RESULTS"]) if os.environ.get("BANKING77_RESULTS")
           else HERE / "results" if DATASET == "banking77" else HERE / "results" / DATASET)  # committed
SOURCE = CFG["base"]
SHA256 = CFG["files"]
#: the LLM arms run on a stratified sample of the test set: this many per intent
PER_INTENT = CFG["per_intent"]
SEED = 77


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def _checked(name: str) -> Path:
    path = DATA / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SHA256[name]:
        raise SystemExit(f"{path} has sha256 {digest}, not the pinned {SHA256[name]}: run fetch.py again")
    return path


def read(name: str) -> list[dict]:
    """banking77's CSV files: text, category."""
    with _checked(name).open(newline="", encoding="utf-8") as f:
        return [{"text": " ".join(r["text"].split()), "intent": r["category"]} for r in csv.DictReader(f)]


def _raw() -> tuple[list[dict], list[dict]]:
    if DATASET == "banking77":
        return read("train.csv"), read("test.csv")
    # CLINC150: [text, intent] pairs; the in-scope splits only (the oos_* splits are a separate question)
    d = json.loads(_checked("data_full.json").read_text())
    rows = lambda pairs: [{"text": " ".join(t.split()), "intent": i} for t, i in pairs]  # noqa: E731
    return rows(d["train"]), rows(d["test"])


def split() -> tuple[list[dict], list[dict], int]:
    """Train, and test without the texts that also occur in train (7 in banking77)."""
    train, test = _raw()
    seen = {norm(r["text"]) for r in train}
    kept = [dict(r, qid=f"t{i:04d}") for i, r in enumerate(test) if norm(r["text"]) not in seen]
    return train, kept, len(test) - len(kept)


def sample(test: list[dict]) -> list[dict]:
    """PER_INTENT queries per intent, drawn with SEED: the same sample for every arm."""
    by = defaultdict(list)
    for r in test:
        by[r["intent"]].append(r)
    rng = random.Random(SEED)
    out = []
    for intent in sorted(by):
        out += rng.sample(by[intent], PER_INTENT)
    return out


def labels(train: list[dict]) -> list[str]:
    return sorted({r["intent"] for r in train})


# ── statistics ──────────────────────────────────────────────────────────────

def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def share(flags: list[bool]) -> dict:
    k, n = sum(flags), len(flags)
    return {"n": n, "right": k, "accuracy": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    """Exact two-sided McNemar on paired outcomes: only the discordant pairs count."""
    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    if n == 0:
        return {"only_first_right": 0, "only_second_right": 0, "p": 1.0}
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {"only_first_right": only_a, "only_second_right": only_b, "p": float(f"{min(1.0, 2 * tail):.3g}")}


def ece(pairs: list[tuple[float, bool]], bins: int = 10) -> dict:
    """Expected calibration error of a stated probability against being right."""
    buckets = defaultdict(list)
    for p, ok in pairs:
        buckets[min(bins - 1, int(p * bins))].append((p, ok))
    total, err, table = len(pairs), 0.0, []
    for b in sorted(buckets):
        xs = buckets[b]
        conf = sum(p for p, _ in xs) / len(xs)
        acc = sum(ok for _, ok in xs) / len(xs)
        err += len(xs) / total * abs(conf - acc)
        table.append({"bin": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "n": len(xs),
                      "stated": round(conf, 3), "right": round(acc, 3)})
    return {"ece": round(err, 4), "bins": table}


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))], 1)


def jsonl(path: Path) -> dict[str, dict]:
    """A resumable run file: one JSON object per line, keyed by qid (the last line wins)."""
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["qid"]] = r
    return out
