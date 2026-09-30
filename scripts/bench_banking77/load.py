"""Load banking77's TRAIN split into Aito. A DRY RUN unless --apply.

Only the 10,003 training queries go in; the test split never does, so every
prediction the benchmark scores is on a query Aito has not seen.

By default this makes (or, with --reload, refills) one collection,
`banking77_train`, in a branch environment `banking77` of the database in
AITO_API_URL, and touches nothing else. It refuses master unless --master is
given, which is for a database of your own that holds nothing else.

    uv run --with 'aitoai>=1.0' python scripts/bench_banking77/load.py            # dry run
    uv run --with 'aitoai>=1.0' python scripts/bench_banking77/load.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys

from common import DATASET, HERE, split

sys.path.insert(0, str(HERE.parent.parent))
from src.config import load_config  # noqa: E402  (reads AITO_API_URL / AITO_API_KEY, and .env if present)

COLLECTION = f"{DATASET}_train"
SCHEMA = {"type": "collection", "columns": {
    "query_id": {"type": "String"},
    "text": {"type": "Text", "analyzer": "english"},
    "intent": {"type": "String"},
}}


def client(env: str | None):
    from aito.v2 import Client
    cfg = load_config()
    db = cfg.aito_url.split("/env/")[0]
    return db, Client(db, cfg.aito_key, env=env) if env else Client(db, cfg.aito_key)


def main() -> int:
    from aito.v2 import Error

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", default=os.environ.get("BANKING77_ENV", DATASET),
                    help="branch environment to load into (default: BANKING77_ENV, else the dataset name)")
    ap.add_argument("--master", action="store_true", help="load into master (a database of your own only)")
    ap.add_argument("--apply", action="store_true", help="perform the writes (default: dry run)")
    ap.add_argument("--reload", action="store_true", help=f"drop and refill {COLLECTION} if it exists")
    ap.add_argument("--check", action="store_true", help="only check the training data is loaded, in full")
    args = ap.parse_args()
    wants_master = args.env.strip().lower() in ("", "master", "env.master")
    env = None if (args.master or wants_master) else args.env.strip()
    if env is None and not args.master and not args.check:
        sys.exit("refusing master: pass --master explicitly, and only for a database of your own")

    train, test, dropped = split()
    rows = [{"query_id": f"r{i:05d}", "text": r["text"], "intent": r["intent"]} for i, r in enumerate(train)]
    db, root = client(None)
    exists = True
    if env:
        envs = root.list_envs()
        listed = envs.get("envs", envs.get("data")) if isinstance(envs, dict) else None
        if not isinstance(listed, list):
            sys.exit("cannot read the environment list; stopping")
        exists = env in {e.get("name") for e in listed}
    target = client(env)[1] if exists else root
    tables = set(target.get_schema().get("schema", {}))
    has = COLLECTION in tables
    if args.check:
        total = target.query({"from": COLLECTION, "limit": 0})["total"] if has and exists else None
        if total == len(rows):
            print(f"ok: {COLLECTION} holds all {total} training queries")
            return 0
        print(f"not loaded: {COLLECTION} {'has ' + str(total) + ' rows' if total is not None else 'is missing'}; "
              f"expected {len(rows)}. Load it: uv run --with 'aitoai>=1.0' python {__file__} --apply")
        return 1
    if has and not args.reload:
        sys.exit(f"refusing: {COLLECTION} already exists there; pass --reload to drop and refill it")

    where = f"{db}/env/{env}" if env else f"{db} (master)"
    print(f"target: {where}  ({'exists' if exists else 'new branch off master'})")
    print(f"  - {'drop and recreate' if has else 'create'} collection '{COLLECTION}' (nothing else is touched)")
    print(f"  - upload {len(rows)} training queries; the {len(test)} test queries stay out "
          f"({dropped} test texts that also occur in train are excluded from scoring)")
    if not args.apply:
        print("dry run: nothing written.")
        return 0

    if env and not exists:
        root.branch_env(env)
    _, c = client(env)
    if env and c.env != env:
        sys.exit(f"client is scoped to {c.env!r}, not {env!r}; stopping before any write")
    if has:
        try:
            c.delete_collection(COLLECTION)
        except Error as err:
            if not err.is_not_found:
                raise
    c.create_collection(COLLECTION, SCHEMA["columns"])
    c.upload_entries(COLLECTION, rows, batch_size=1000)
    c.optimize(COLLECTION)
    total = c.query({"from": COLLECTION, "limit": 0})["total"]
    if total != len(rows):
        sys.exit(f"{total} rows in Aito, {len(rows)} expected: re-run with --reload")
    print(f"done: {total} rows in {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
