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
| `support_tickets` | 3,850 | `customer → customers`, `product → products`, `kb_article → kb_articles` (nullable) |
| `support_steps` | 18,810 | `ticket → support_tickets` |

The **newest 150 tickets** (and their steps) are held out as the **incoming queue**:
never loaded, and committed at `src/data/support_incoming.json` for the app. The
envelope view predicts on those, so Aito has not seen the tickets it is judged on, and
their recorded truth is what the view compares against. The measurements below are
over all 4,000.

Tickets run from 2026-03-02 to 2026-09-27. `month` (YYYY-MM) is the time axis for
drift; `created_at` is the exact stamp.

## Planted causes, and what they measure

`python3 lifts.py` measures each effect from the written files only (plus the
replayed Northwind rows), never from the generator's internals. Numbers for the
default seed; "differs" means the 95% Wilson intervals don't overlap.

| story | planted | measured |
|---|---|---|
| category from words | topic phrases share vocabulary; 12% of tickets mix two topics | 0 of 172 common words is a perfect rule; "invoice" 0.79, "sync" 0.85, "report" 0.32 |
| priority | mostly urgency words; a little category, plan and size | high 0.62 with urgency words vs 0.17 without; Enterprise plan 0.33 vs Free 0.23; bug 0.32 vs how-to 0.21 (all differ) |
| drift | from 2026-07, 80% of `login` issues are fixed by `sso_reconnect`, not `reset_password` | `sso_reconnect` on login issues: 0.00 before, 0.82 after; on all access tickets: 0.00 before, 0.39 after |
| next step | each resolution is a step sequence ending in `done`, with 15% detours | e.g. bug `check_pipeline → rerun_sync` 0.83; every path's last step → `done` 1.00. After `reproduce`, a bug splits 0.43 / 0.57 by its `issue` (crash or wrong data) |
| detractor risk | repeat ticket in 30 days, first response >24h, Red account | base 0.20; repeat 0.31, >24h 0.32, Red 0.31 (Green 0.16); each differs from the base |
| recovery lever | assigned at random, so its effect is causal; the best action depends on size | detractor rate, best vs none: SMB credit 0.11 vs 0.30; Mid-market callback 0.11 vs 0.26; Enterprise CSM outreach 0.08 vs 0.28 (each differs) |
| upsell | offered at random on 30% of tickets from accounts that haven't churned | accepted 0.36 at `adoption_band` high vs 0.11 at low; Red accounts 0.02 (base 0.23) |
| **control** | the ticket `channel` has **no** effect on `nps_after` | each channel against the rest: \|z\| < 1.96 (email −1.72, chat 0.22, portal 0.64, phone 0.89); lift 0.91 to 1.05 |

The control is what makes the rest believable. `tests/test_support_fixture.py` fails
if it stops being null, and it also plants a +0.07 chat effect (`control_leak`) to
prove the check then fails. Email's −1.72 is chance at this sample size, not a
planted effect.

## Inputs and targets: what a demo may use to predict what

Some columns are recorded *after* the thing a demo would predict, or give it away.
Using them as inputs would make a prediction look better than it is:

| to predict | do not use as an input | why |
|---|---|---|
| `category`, `resolution` | `resolution`, `kb_article`, `kb_article.resolution` | the article is the resolution's article; the resolution determines the category |
| `priority` | `first_response` | response time follows priority |
| `nps_after` | `csat_band` | both are recorded after the ticket; csat is derived from the NPS answer |
| `upsell_accepted` | (filter to `upsell_offered = yes`) | `upsell_accepted` is empty when no offer was made |
| the next step | `ticket.resolution`, `ticket.kb_article` | the resolution picks the path; use `ticket.issue` and `category` |

Also true of this data, and worth saying in any view built on it:

- **The text is templated.** No single word decides the category, but each opening
  clause belongs to exactly one category, so an LLM or a nearest-neighbour match reads
  the category off it easily. The cache story here is cost and speed, not that the
  LLM gets category wrong.
- **`sender_domain` identifies the customer** for the 60% of tickets from a corporate
  address; the rest come from a freemail domain.
- **`repeat_30d` is undercounted in March** (no tickets before 2026-03-02).
- Tickets from customers that later churned are included; upsells are never offered
  to them.

## Use

```bash
python3 scripts/support_fixture/generate.py            # writes data/ and src/data/support_incoming.json (byte-identical every run)
python3 scripts/support_fixture/lifts.py               # measure the planted effects
uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py           # dry run: prints the plan
uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py --apply   # writes (Antti runs it)
```

`load.py` writes only to a branch environment (default `support`), branched off
master so it keeps `customers` and `products` for the links. It only ever creates,
drops or fills the three support collections, refuses master, refuses an existing
environment unless `--reload` is given, and checks that every linked customer and
product exists before writing.
