"""Load the `support` fixture into a branch environment. A DRY RUN unless --apply.

The support tables link to the Northwind `customers` and `products` already on
master, so the branch KEEPS everything it inherits from master and only adds
the three support collections. It never drops a table it didn't create, and it
refuses master: going live on master is a separate decision
(docs/design/support-agent.md).

    python3 scripts/support_fixture/generate.py
    uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py            # dry run
    uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py --apply    # writes (Antti)

The database URL and key come from src/config.py, like every other script in
this repo; a dry run needs only a read key.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from src.config import load_config  # noqa: E402

#: parents before children: kb_articles is a link target of support_tickets
ORDER = ["kb_articles", "support_tickets", "support_steps"]
#: must already exist in the environment (they come from master)
LINK_TARGETS = ["customers", "products"]


def main() -> int:
    from aito.v2 import Client, Error

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", default="support")
    ap.add_argument("--apply", action="store_true", help="perform the writes (default: dry run)")
    args = ap.parse_args()
    if args.env in ("", "master", "env.master"):
        sys.exit("refusing to load into master: use a branch environment (--env)")

    cfg = load_config()
    db = cfg.aito_url.split("/env/")[0]  # the database root, whatever AITO_ENV says
    schema = json.loads((HERE / "schema.json").read_text())
    data = {n: json.loads((HERE / "data" / f"{n}.json").read_text()) for n in ORDER}
    assert list(schema) == ORDER, "schema.json and ORDER disagree"

    root = Client(db, cfg.aito_key)
    envs = root.list_envs()
    exists = args.env in {e["name"] for e in envs.get("envs", envs.get("data", []))}
    tables = set((Client(db, cfg.aito_key, env=args.env) if exists else root).get_schema().get("schema", {}))
    missing = [t for t in LINK_TARGETS if t not in tables]
    if missing:
        sys.exit(f"refusing: link targets {missing} are not in {'env ' + args.env if exists else 'master'}")

    plan = [] if exists else [f"branch environment '{args.env}' off master (keeps all {len(tables)} master tables)"]
    for n in ORDER:
        plan.append(f"{'drop and recreate' if n in tables else 'create'} collection '{n}'")
        plan.append(f"upload {len(data[n])} rows into '{n}', optimize, check the count")
    print(f"target: {db}/env/{args.env}  ({'exists' if exists else 'new'})")
    for step in plan:
        print("  -", step)
    if not args.apply:
        print("dry run: nothing written.")
        return 0

    if not exists:
        root.branch_env(args.env)
    env = Client(db, cfg.aito_key, env=args.env)  # every write below is scoped to the branch
    assert env.env == args.env
    for n in reversed(ORDER):  # children first, so no link points at a dropped table
        if n in tables:
            try:
                env.delete_collection(n)
            except Error as err:
                if not err.is_not_found:
                    raise
    for n in ORDER:
        env.create_collection(n, schema[n]["columns"])
        inserted = env.upload_entries(n, data[n], batch_size=1000)
        env.optimize(n)
        total = env.query({"from": n, "limit": 0})["total"]
        assert total == len(data[n]), f"{n}: {total} rows in Aito, {len(data[n])} generated"
        print(f"  {n:16} {inserted} rows")
    print(f"done: {db}/env/{args.env}/api/v2/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
