"""Shared pieces of the banking77 benchmark: the pinned data, the pinned sample,
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
DATA = HERE / "data"          # downloaded, not committed (see .gitignore)
RESULTS = Path(os.environ["BANKING77_RESULTS"]) if os.environ.get("BANKING77_RESULTS") else HERE / "results"  # committed: every number the page shows comes from here

#: PolyAI's banking77 (CC BY 4.0), pinned by content
SOURCE = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data"
SHA256 = {
    "train.csv": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
    "test.csv": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
}
#: the LLM arms run on a stratified sample of the test set: this many per intent
PER_INTENT = 8
SEED = 77


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def read(name: str) -> list[dict]:
    path = DATA / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SHA256[name]:
        raise SystemExit(f"{path} has sha256 {digest}, not the pinned {SHA256[name]}: run fetch.py again")
    with path.open(newline="", encoding="utf-8") as f:
        return [{"text": " ".join(r["text"].split()), "intent": r["category"]} for r in csv.DictReader(f)]


def split() -> tuple[list[dict], list[dict], int]:
    """Train, and test without the texts that also occur in train (7 in banking77)."""
    train, test = read("train.csv"), read("test.csv")
    seen = {norm(r["text"]) for r in train}
    kept = [dict(r, qid=f"t{i:04d}") for i, r in enumerate(test) if norm(r["text"]) not in seen]
    return train, kept, len(test) - len(kept)


def sample(test: list[dict]) -> list[dict]:
    """PER_INTENT queries per intent, drawn with SEED: the same 616 for every arm."""
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
    return {"only_first_right": only_a, "only_second_right": only_b, "p": round(min(1.0, 2 * tail), 6)}


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
