# Agent demo v2 migration

The application supports both API versions. Production remains on v1 while
scoped driver rates and text retrieval are validated on the existing v2 branch.
The private work tracker carries the instance-specific findings and core issue
references; this guide describes how to reproduce the checks and finish cutover.

## Acceptance checks

```bash
./do v2-check    # read-only correctness gate on the existing env/v2 branch
./do v2-probe    # op-level v1/master versus v2/branch difference report
./do v2-parity   # deterministic HTTP-route difference report
./do test       # local regression tests
./do test-book  # replay the accepted snapshots
./do build
```

`v2-check` verifies that branch tables use the v2 storage engine and that table
sets and row counts match master. Counts alone do not establish content identity.
It also checks golden intents, sensitive-action handoff, probability ranges,
basic route contracts and the following two semantic properties:

- Scoped `_relate` frequencies and probabilities must describe the emitted
  `condition` and `related` labels. The check uses independent `_query` counts
  to distinguish an outcome rate from its inverse conditional probability.
- Similarity retrieval must retain known evidence when an unknown word is added
  to the probe. Known-token and fully-matching multi-token controls are included.

The two focused repros are also runnable separately:

```bash
uv run python -m scripts.v2_relate_check
uv run python -m scripts.v2_retrieval_check
```

They only read the existing demo fixtures; they never create, migrate or write
tables. Treat a failing semantic check as a cutover blocker, not a difference
to accept blindly. File core failures with a reproducible query rather than
compensating for an inconsistent engine contract in the demo.

The parity tools retain nonzero exit codes for differences. A rebuilt inference
engine need not produce bit-identical probabilities. Review changed intents,
parameters, handoff decisions, estimates, rankings and rendered rates alongside
the acceptance gate. Passing the gate is necessary, but does not replace that
review or a UI smoke test. The Manufacturing/Analytics case deliberately permits
an empty reference list: it checks the old zero-row-conjunct error.

`/api/route` is excluded from the deterministic sweep because it makes paid LLM
calls. Its Aito shortlist query remains covered by the op-level probe; smoke-test
the complete LLM-backed flow separately.

## Configuration

`AITO_API_VERSION` selects `v1` (default) or `v2`. `AITO_ENV` selects an existing
copy-on-write branch by appending `/env/<name>` to the database URL; unset means
master. Explicit shell target variables override `.env` target values:

```bash
AITO_API_VERSION=v2 AITO_ENV=v2 ./do dev
```

Credentials retain the existing `.env` precedence. Never print keys in probes.
The optional browser client supports `NEXT_PUBLIC_AITO_API_VERSION` and
normalizes `feature`/`$value`; the app currently uses the Python backend instead.
Always inspect the deployed server revision and per-table engine metadata before
assuming a core fix is available: selecting `/api/v2` alone does not migrate the
storage engine.

## Snapshot migration

Schema and match/retrieval books use the configured API version. Committed
baselines remain v1 until v2 correctness is established. The retrieval book
asserts recall as well as direct-answer accuracy, so a successful `_match`
answer cannot conceal irrelevant retrieved rows.

The books previously passed `assertln` arguments in the wrong order (message
before condition), allowing false conditions to print `ok`. They now pass the
boolean first.

Capture only the **read-only** books on the branch for review:

```bash
AITO_API_VERSION=v2 AITO_ENV=v2 uv run booktest -s \
  book/test_01_aito_schema_book.py book/test_03_match_book.py
```

Inspect output and assertions before accepting snapshots. `-s` captures missing
HTTP snapshots; `-S` refreshes existing ones. Neither establishes correctness.
Restore unaccepted HTTP captures before committing.

**Do not bulk re-record `book/test_02_resolution_scorecard_book.py` on the demo
instance.** It recreates `resolutions` through the offline benchmark's own client.
That harness is outside this app migration; normal replay is safe.

## Production cutover

1. Resolve the core failures recorded in the private work tracker and verify
   that the fixes are deployed to the server under test.
2. Run `v2-check`, review probe/parity deltas, and review v2 book snapshots.
3. Smoke-test the v2 UI and LLM-backed surfaces separately. Record which
   agent-memory claims are demonstrated before writing launch copy.
4. Check data freshness/content before promoting the branch; matching counts
   are insufficient if master has received writes since branching.
5. In the platform's separate PR, set the agent demo's `AITO_API_VERSION: v2`
   and either `AITO_ENV: v2` (explicit branch) or promote the validated branch to
   master and omit `AITO_ENV`. Rebuild/deploy through the platform workflow.
   Promotion also changes data for other master readers: it is a cutover action,
   never a diagnostic step.
6. Update the v1 examples in README, CHEATSHEET, docs/use-cases and AppShell with
   the production switch. They describe the still-live v1 surface today. If the
   optional browser client is enabled, set its build-time version to v2 too.
7. Check production health, semantic output and LLM-backed flows. A person
   closes the work ticket after review; agents leave it at `review`.

The historical August gap report is retained in the existing git history. Its
API-contract claims are not a current readiness assessment. Offline benchmark
harnesses remain separately scoped migrations.
