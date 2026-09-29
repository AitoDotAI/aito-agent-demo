"""Load the `support` fixture into a branch environment. A DRY RUN unless --apply.

The support tables link to the Northwind `customers` and `products` already on
master, so the branch KEEPS everything it inherits from master and only adds
the four support collections. It only ever creates, drops or fills those four,
refuses master (going live on master is a separate decision,
docs/design/support-agent.md), refuses an existing environment unless --reload
is given, and checks every linked customer and product exists before writing.

    python3 scripts/support_fixture/generate.py
    telco-tool-routing-bench/run-py scripts/support_fixture/embed.py              # the pinned vectors
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
sys.path.insert(0, str(HERE))
from src.config import load_config  # noqa: E402

#: parents before children: kb_articles and support_contacts are link targets of support_tickets
ORDER = ["kb_articles", "support_contacts", "support_tickets", "support_steps"]
#: must already exist in the environment (they come from master)
LINK_TARGETS = ["customers", "products"]


def main() -> int:
    from aito.v2 import Client, Error

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", default="support")
    ap.add_argument("--apply", action="store_true", help="perform the writes (default: dry run)")
    ap.add_argument("--data", default=str(HERE / "data"),
                    help="the generated files (and support_vectors.json) to load; default data/")
    ap.add_argument("--reload", action="store_true",
                    help="allow an existing environment: drop and refill its four support collections")
    args = ap.parse_args()
    args.env = args.env.strip()
    if args.env.lower() in ("", "master", "env.master"):
        sys.exit("refusing to load into master: use a branch environment (--env)")

    cfg = load_config()
    db = cfg.aito_url.split("/env/")[0]  # the database root, whatever AITO_ENV says
    schema = json.loads((HERE / "schema.json").read_text())
    data_dir = Path(args.data)
    data = {n: json.loads((data_dir / f"{n}.json").read_text()) for n in ORDER}
    if list(schema) != ORDER:
        sys.exit("schema.json and ORDER disagree")
    # the vectors: made by embed.py with the pinned model, one per ticket and article
    from embed import DIMENSIONS, MODEL, REVISION, VECTORS
    vectors = data_dir / VECTORS.name
    if not vectors.exists():
        sys.exit(f"no {vectors}: run embed.py first (see the docstring)")
    vec = json.loads(vectors.read_text())
    if (vec.get("model"), vec.get("revision"), vec.get("dimensions")) != (MODEL, REVISION, DIMENSIONS):
        sys.exit(f"{VECTORS.name} was made with {vec.get('model')}@{vec.get('revision')}, "
                 f"not the pinned {MODEL}@{REVISION}: re-run embed.py")
    for n, key, id_field in (("support_tickets", "tickets", "ticket_id"), ("kb_articles", "kb_articles", "article_id")):
        missing = [r[id_field] for r in data[n] if r[id_field] not in vec[key]]
        if missing:
            sys.exit(f"{len(missing)} {n} rows have no vector (e.g. {missing[:3]}): re-run embed.py")
        data[n] = [{**r, "embedding": vec[key][r[id_field]]} for r in data[n]]

    root = Client(db, cfg.aito_key)
    envs = root.list_envs()
    listed = envs.get("envs", envs.get("data")) if isinstance(envs, dict) else None
    if not isinstance(listed, list):
        sys.exit(f"cannot read the environment list (got keys {sorted(envs) if isinstance(envs, dict) else type(envs)}); stopping")
    exists = args.env in {e.get("name") for e in listed}
    if exists and not args.reload:
        sys.exit(f"refusing: env '{args.env}' already exists. Pass --reload to drop and refill its four "
                 "support collections (nothing else in it is touched), or pick a new --env.")
    source = Client(db, cfg.aito_key, env=args.env) if exists else root
    tables = set(source.get_schema().get("schema", {}))
    missing = [t for t in LINK_TARGETS if t not in tables]
    if missing:
        sys.exit(f"refusing: link targets {missing} are not in {'env ' + args.env if exists else 'master'}")
    # every link must resolve: the replayed Northwind ids against what is really there
    known = {t: {h[k] for h in source.query({"from": t, "select": [k], "limit": 10000})["hits"]}
             for t, k in (("customers", "customer_id"), ("products", "product_id"))}
    dangling = sorted({r[f] for n, fields in (("support_tickets", ("customer", "product")), ("support_contacts", ("customer",)))
                       for r in data[n] for f in fields
                       if r[f] not in known["customers" if f == "customer" else "products"]})
    if dangling:
        sys.exit(f"refusing: tickets link to {len(dangling)} id(s) that don't exist, e.g. {dangling[:3]}; "
                 "was seed_company.py changed since the fixture was generated?")

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
    if env.env != args.env:
        sys.exit(f"client is scoped to {env.env!r}, not {args.env!r}; stopping before any write")
    for n in reversed(ORDER):  # children first, so no link points at a dropped table
        if n in tables:
            try:
                env.delete_collection(n)
            except Error as err:
                if not err.is_not_found:
                    raise
    for n in ORDER:
        env.create_collection(n, schema[n]["columns"])
        inserted = env.upload_entries(n, data[n], batch_size=400)  # vectors: stay well under the 10 MB request cap
        env.optimize(n)
        total = env.query({"from": n, "limit": 0})["total"]
        if total != len(data[n]):
            sys.exit(f"{n}: {total} rows in Aito, {len(data[n])} generated. The env is half-loaded; "
                     "re-run with --reload.")
        print(f"  {n:16} {inserted} rows")
    print(f"done: {db}/env/{args.env}/api/v2/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
