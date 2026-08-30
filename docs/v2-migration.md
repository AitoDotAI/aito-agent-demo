# Migrating the agent demo onto `/api/v2`

Status as of **2026-08-15**: the demo *runs* on v2, but **cannot cut over yet** —
two core defects (G1, G2) change behaviour, one of them silently.

This document is the "file each break as a core gap" half of the migration task.
The instruments that produce it are committed:

```bash
./do v2-probe     # op-level: every Aito query shape, v1 vs v2   (exit = #diffs)
./do v2-parity    # route-level: every /api/* response, v1 vs v2 (exit = #diffs)
```

Re-run both as core lands fixes. When they report zero, flip the env (below) and
the demo is on v2.

## How this repo targets v2

Nothing in the code hardcodes an API version any more. Two env vars, both
defaulting to today's production behaviour:

| Var | Default | Meaning |
|---|---|---|
| `AITO_API_VERSION` | `v1` | `v1` or `v2` — the REST path prefix |
| `AITO_ENV` | *(unset)* | Aito environment (copy-on-write branch); unset = `env.master` |

`AITO_ENV` is folded into the base URL by `src/config.py`, because an Aito
environment is selected **purely by URL path** — never by a body field, query
param, or header:

```
https://shared.aito.ai/db/aito-agent-demo             → env.master   (production)
https://shared.aito.ai/db/aito-agent-demo/env/v2      → the v2 branch
```

Production sets neither var, so it is byte-identical to before this change.

## The separate db env

The v2 work has its own database environment, branched from production:

```bash
curl -X POST "$AITO_API_URL/api/v2/_envs" \
  -H "x-api-key: $AITO_RW_KEY" -H 'content-type: application/json' \
  -d '{"name":"v2","basedOn":"env.master"}'
```

It is **copy-on-write — no data was copied** and `env.master` is untouched.
Verified identical at branch time (`resolutions` 4000, `invoices` 2600,
`tool_calls` 300, 12 tables). Writes to `env/v2` diverge from master; master
never sees them.

Two properties worth knowing:

- **There is no env-scoped API key.** The same key that reads/writes master
  reads/writes every env. The demo's production key is read-only, so it cannot
  damage the branch either.
- **Cutover is an atomic promote**, not a re-import:
  `POST /api/v2/_envs/v2/promote` swaps the branch into master. So the eventual
  v2 migration needs no data migration at all — which is the main reason to do
  the work in an env rather than a second database.

To run locally against it:

```bash
AITO_API_VERSION=v2 AITO_ENV=v2 ./do dev
```

## The storage engine — migrate it, or you are testing the adapter

**`/api/v2` is engine-dispatched.** A `type: "table"` created through the v1 path
is *rep1* (`engine: v1`); the v2 endpoints run the **v1 pipeline** for it. Only a
*rep2* table (`engine: v2`) runs native v2 code.

So pointing a client at `/api/v2` proves very little on its own — it exercises the
adapter, not the engine. Everything in this document up to 2026-08-29 was measured
that way, and migrating the engine changed several answers. Migrate first, then
compare:

```bash
# atomic across tables, and warms them inside the same transaction
curl -X POST "$AITO_API_URL/env/v2/api/v2/data/_modify" \
  -H "x-api-key: $AITO_RW_KEY" -H 'content-type: application/json' \
  -d '{"operations":[{"migrate":"customers","engine":"v2"}, …]}'
# → {"migrated": 12, "warmedLinkageFields": 9}
```

Per-table equivalent: `POST /api/v2/schema/{table}/_migrate` `{"engine":"v2"}`.
Both are idempotent; there is no reverse migration.

This env branch's 12 tables were migrated on 2026-08-29 (row counts verified
unchanged). **Production master is deliberately still rep1** — migrating it is
part of the cutover, not preparation for it.

Note you currently **cannot tell which engine a table is on**: the `engine` field
was removed from the schema response (aito-core#1224). Track what you migrated.

## Core gaps

All eight are filed against `AitoDotAI/aito-core` as issues **#1061–#1068**. A ninth (#1069, a v2 schema-union rejection breaking the company-ai search index) was found alongside these but is not a demo gap.

Ordered by whether they block the cutover. G1/G2 are the ones that matter.

### G1 — BLOCKING · `bit & operation requires same sized bit sets`

Filed as **aito-core#1061**.

An AND that combines a table-sized bitset with an index covering fewer rows
returns **HTTP 400 with an internal error message** instead of a result.

```
POST /api/v2/_query
{"from":"resolutions","where":{"intent":"refund","customer":"cust_0001"},"limit":0}
→ 400 {"code":"request.invalid",
       "message":"bit & operation requires same sized bit sets, found: 4000, 0"}

v1, same data → 200 {"total": 0}
```

Reproduces on `_query`, `_search` and `_predict`, via every one of:

| Trigger | Example | Sizes reported |
|---|---|---|
| Implicit AND where one conjunct matches 0 rows | `{"intent":"refund","customer":"cust_0001"}` | `4000, 0` |
| Explicit `$and`, same | `{"$and":[{"intent":"refund"},{"customer":"cust_0001"}]}` | `4000, 0` |
| Any predicate on a **nullable** column | `{"location":"Helsinki"}` | `4000, 3954` |
| `$has` on a Text column with empty values | `{"text":{"$has":"broadband"}}` | `4000, 3987` |

`$or` is unaffected. The non-zero second size (3954 = non-null `location`
rows, 3987 = rows with a non-empty `text`) says the operand bitset is sized to
the *index* rather than to the table, and the AND never aligns them.

**Demo impact:** `/api/opportunity?industry=Manufacturing&service_line=Analytics`
→ **502** (a 4-field where where one conjunct is empty).
`/api/company-360` → `causes` and `drivers` silently empty, because
`_relate_drivers` catches the error and degrades.

This is the single blocker: `resolutions` has three nullable columns and every
route filters on multiple fields.

### G2 — BLOCKING · a bare string on a `Text` column means something different

Filed as **aito-core#1062**.

Same rows, same query, different answer — and **no error**:

```
POST _predict {"from":"resolutions",
               "where":{"text":"my broadband keeps dropping every evening"},
               "predict":"intent","limit":3}

v1 → repair_help    0.9474   ← correct
v2 → cancel_service 0.5756   ← wrong
```

Isolated to the API version, not the environment — all four combinations were
tested and the branch makes no difference:

| | `/api/v1` | `/api/v2` |
|---|---|---|
| `env.master` | repair_help 0.9474 | cancel_service 0.5756 |
| `env/v2` | repair_help 0.9474 | cancel_service 0.5756 |

The inference engine agrees; only the implicit coercion differs. With explicit
`$has` the two surfaces are **byte-identical** (`refund 0.4265 / cancel_service
0.3446` on both), and v2 is not simply ignoring the evidence either — with no
`where` at all it returns a flat 0.1667 prior, so it applies *some*, different,
evidence.

**Demo impact:** `/api/resolve` — the flagship route — returns a wrong intent on
both test tickets. This is the dangerous one: 200 OK, plausible output, wrong
answer. Any demo that migrates without a golden-output diff will ship it.

### G3 — contract · `feature` → `$value`, inconsistently

Filed as **aito-core#1063**.

v2 renames the predicted value on `_predict`/`_recommend` hits and drops `field`:

```
v1 hit: {"$p":0.9474, "field":"intent", "feature":"repair_help"}
v2 hit: {"$p":0.5756, "$value":"cancel_service"}
```

`select:["$p","feature","$why"]` → 400 `no such field 'feature'`.

But **`_match` was not renamed** — its v2 hits still carry `field`/`feature`. So
within one API version, `_predict` and `_match` disagree about what to call the
same thing. Whichever name wins, it should be the same on both.

*Shimmed here:* `AitoClient` publishes both spellings on every hit and rewrites
`feature` → `$value` in `select`, so `src/app.py` reads one name on either
surface. `$why` itself is byte-identical between versions.

### G4 — contract · `_relate` proposition shape

Filed as **aito-core#1064**.

```
v1: {"related":{"plan":{"$has":"Free"}}, "condition":{"churned":{"$has":"yes"}}}
v2: {"related":{"plan":"Free"},          "condition":{"churned":"yes"}}
```

v2's spelling is nicer, but it is a breaking change and undocumented.

Worse, for the `$on` form v2 echoes the **whole `$on` argument** back as
`condition`:

```
v2: "condition": {"$on":[{"churned":"yes"},{"size":"SMB"}]}
```

where v1 returns the individual driver condition. The `$on` form exists so each
hit names one driver and `ps.pOnCondition` gives its within-segment rate; echoing
the input makes scoped drivers unreadable. *Partially shimmed* (`_why_props` now
accepts bare values); the `$on` echo is not shimmable.

### G5 — numeric · `_relate` statistics differ

Filed as **aito-core#1065**.

Same query, same rows:

| | `lift` | `fs.f` |
|---|---|---|
| v1 | 1.446849 | 330.6875 |
| v2 | 1.462282 | 327.0 |

v1's fractional `f` suggests smoothing that v2 drops for a raw count. Probably
deliberate — but it is a silent numbers change in a value demos display, so it
needs to be a documented decision rather than a diff someone finds later.

### G6 — gap · no `orderBy` for similarity-ranked search

Filed as **aito-core#1066**.

Every spelling fails on v2:

```
orderBy "$similarity" → 400 Field not found: $similarity
orderBy "$score"      → 400 Field not found: $score
orderBy "$p"          → 400 prediction proposition can only be used with
                            contextful instance examination
```

The last is the D4 wall from `docs/aito-sql-dialect.md`, reached through REST
rather than SQL — worth noting on that decision, since it shows D4 is not
SQL-specific.

### G7 — gap · `POST /_similarity` removed

Filed as **aito-core#1067**.

404 `The path you requested [/_similarity] does not exist` on v2, with no
documented replacement. `book/test_03_match_book.py` uses it to contrast match
vs. plain retrieval. If `_match` is meant to subsume it, that should be written
down; if it is a removal, it needs a migration note.

### G8 — cosmetic · schema response shape

Filed as **aito-core#1068**.

v2 omits `nullable: false` (present in v1) and adds `engine: "v1"` per table.
Harmless, but `/api/schema` is rendered by the AitoPanel's "verify yourself"
link, so it is user-visible.

## What is done here

- `src/config.py` — `AITO_API_VERSION` + `AITO_ENV`, both defaulting to prod's
  current behaviour
- `src/aito_client.py` — version-aware paths; G3 normalisation both directions
- `src/app.py` — `_why_props` accepts v2's bare-value propositions (G4, partial)
- `scripts/seed_*.py` — version-aware, so the branch can be re-seeded on v2
- `scripts/v2_probe.py`, `scripts/v2_parity.py` + `./do` targets

## What is left

1. Core fixes G1 and G2 (blocking), decisions on G4–G7.
2. Re-run `./do v2-probe` and `./do v2-parity` — both must reach zero.
3. Re-record the booktest snapshots, which are pinned to v1 URLs and payloads.
4. Flip `AITO_API_VERSION=v2` in `aito-demo-server`'s `demos.config.yaml`, or
   `POST /api/v2/_envs/v2/promote` and flip only the version.
5. Update the `/api/v1` samples in `README.md`, `CHEATSHEET.md`, `docs/use-cases/`
   and `frontend/` — deliberately left on v1 so the docs match what is live.

The benchmark harnesses (`telco-tool-routing-bench/`, `ticket-assignment-bench/`,
`resolution-scorecard/`) still call v1 directly. They are offline and write their
own tables, so they are out of scope here and unaffected by the cutover.

## Read `api-docs/content/base-v2.md` first

Most of what this document originally called a "v2 gap" was specified behaviour I
had not read, measured against rep1 tables. The spec answers, in one page:

| Thing | Spec says |
|---|---|
| `_estimate` shape | scalar ops carry `{"kind","data"}`; row ops stay bare. Unwrap by shape: `res.kind ? res.data : res.hits` |
| `_estimate` `why` | a **`select`**, not a default — `select: ["estimate","why"]` (portable: v2 takes `estimate` or `value` and echoes the name you asked for) |
| `feature` / `field` | `feature` → `$value`; `field` **removed** by design — it was your own request parameter |
| `orderBy: "$similarity"` | replaced by `$nearest` (vector) or a `$match` where-term; works on rep2 |
| `POST /_similarity` | deliberately not on v2 |
| `engine` in schema | opt-in: `GET /api/v2/schema/{t}?meta` |
| unknown columns | v2 fails loud by design — "a `200` with an empty result always means *no match*, never *unsupported and swallowed*" |

Issues aito-core#1063, #1066, #1067, #1212, #1221 and #1224 were all filed against
this document's earlier claims and are **closed as invalid**.

## What is actually left (2026-08-30)

| | Issue | |
|---|---|---|
| A1 | aito-core#1238 | The **rep1 adapter** under `/api/v2` does not follow the v2 contract: bare v1 `_estimate` envelope, `_match` still emitting the removed `field`/`feature`, no `type:table` strictness, and a malformed `$similarity` error. This is the real residue of the five closed issues, and the reason "point at `/api/v2`" proves nothing until the engine is migrated. |
| A2 | aito-core#1223 | Internal `__cache` appears in `GET /schema` after a migration; querying it returns a raw `ClassCastException`. |
| A3 | aito-core#1225 | `/api/v2/_relate` drops the `ps` block (within-population rates) on both engines. Not covered by the spec either way — an open question, not a confirmed defect. |
| A4 | aito-core#1064 / #1065 | `_relate` proposition shape and statistics. Both spellings are documented as accepted, so #1064 is narrower than filed; #1065's numeric difference is v1-engine vs v2-engine and may simply be the rebuilt engine. |

`_match` ranking differences between the engines are **expected** — rep1 runs the
v1 pipeline, so that comparison is v1-vs-v2 inference, not a regression.

### Where the demo stands

`./do v2-parity` still reports differences, but they are now mostly *engine*
differences (different probabilities from a rebuilt engine) rather than contract
breaks. The remaining contract issue that affects rendering is A3, which zeroes
`/api/company-360`'s driver percentages.
