# The `support` fixture

> **Synthetic data.** Every ticket, step, KB article and outcome here is generated.
> The effects are planted on purpose and measured below; nothing here describes a
> real company or customer.

Phase 1 of [the support-agent design](../../docs/design/support-agent.md): support
tickets with text, their resolution steps and a small KB, **linked to the Northwind
Cloud customers and products** that the /company pages already use. The Northwind
rows are replayed from `scripts/seed_company.py` with its own seed, which reproduces
what is on shared exactly (1500/1500 customers and 3531/3531 usage rows, checked
2026-09-28), so every link resolves and no existing table changes.

| collection | rows | links |
|---|---|---|
| `kb_articles` | 15 | |
| `support_tickets` | 4,000 | `customer → customers`, `product → products`, `kb_article → kb_articles` (nullable) |
| `support_steps` | 15,576 | `ticket → support_tickets` |

Tickets run from 2026-03-02 to 2026-09-27, each with a `created_at`, so drift has a
time axis.

## Planted causes, and what they measure

`python3 lifts.py` measures each effect from the written files only (plus the
replayed Northwind rows), never from the generator's internals. Numbers for the
default seed, with 95% Wilson intervals where a rate is compared:

| story | planted | measured |
|---|---|---|
| category from words | topic phrases share vocabulary; 12% of tickets mix two topics | 0 of 172 common words is a perfect rule; "invoice" 0.80, "sync" 0.90, "report" 0.35 |
| priority | urgency words, category, plan and size | high priority 0.61 with urgency words vs 0.16 without (base 0.24) |
| drift | from 2026-07-01, login tickets are fixed by `sso_reconnect`, not `reset_password` | `sso_reconnect` share 0.00 before (n=143), 0.78 after (n=143) |
| next step | each resolution is a step sequence with 15% detours | e.g. performance `reproduce → profile_query` 0.85; bug `check_pipeline → rerun_sync` 0.87 |
| detractor risk | repeat ticket in 30 days, first response >24h, Red account | base 0.20; repeat 0.32, >24h 0.30, Red 0.31 (Green 0.16) |
| recovery lever | randomly assigned, so its effect is causal; the best action depends on size | detractor rate with the best vs none: SMB credit 0.13 vs 0.23; Mid-market callback 0.17 vs 0.25; Enterprise CSM outreach 0.06 vs 0.27 |
| upsell | offered at random on 30%; accepted by adoption and plan, not by Red accounts | accepted 0.34 at high adoption vs 0.11 at low; Red 0.02 (base 0.21) |
| **control** | the ticket `channel` has **no** effect on `nps_after` | lift 0.96-1.04 across email, chat, portal, phone; every interval covers the base |

The control is what makes the rest believable: `tests/test_support_fixture.py`
fails if it stops being null (checked by planting a +0.07 chat effect).

## Use

```bash
python3 scripts/support_fixture/generate.py            # writes data/ (byte-identical every run)
python3 scripts/support_fixture/lifts.py               # measure the planted effects
uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py           # dry run: prints the plan
uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py --apply   # writes (Antti runs it)
```

`load.py` writes only to a branch environment (default `support`), branched off
master so it keeps `customers` and `products` for the links, and adds only the three
support collections. It refuses master and never drops a table it didn't create.
