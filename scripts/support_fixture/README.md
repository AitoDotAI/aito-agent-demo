# The `support` fixture

> **Synthetic data.** Every contact, ticket, step, KB article and outcome here is
> generated. The effects are planted on purpose and measured below; nothing here
> describes a real company or person.

Phase 1 of [the support-agent design](../../docs/design/support-agent.md): a **B2B
support desk** for Northwind Cloud's accounts. Named contacts, their tickets, the
resolution steps and a small KB, **linked to the Northwind customers and products**
that the /company pages already use. The Northwind rows are replayed from
`scripts/seed_company.py` with its own seed, which reproduces what is on shared
exactly (1500/1500 customers and 3531/3531 usage rows, checked 2026-09-28), so every
link resolves and no existing table changes.

The desk serves 240 active accounts, larger ones more often, with about 50 tickets
each over a year (2025-10-01 to 2026-09-27). That density is what makes an account's
history useful: its contacts, its products and its recurring problems.

| collection | rows | links |
|---|---|---|
| `kb_articles` | 15 | |
| `support_contacts` | 847 | `customer → customers` |
| `support_tickets` | 11,700 | `customer → customers`, `product → products`, `contact → support_contacts` (nullable), `kb_article → kb_articles` (nullable) |
| `support_steps` | 58,710 | `ticket → support_tickets` |

**Vectors.** `support_tickets.embedding` (the ticket text) and `kb_articles.embedding`
(title and body) are 384-dimension cosine `Vector` columns, so similar cases,
hybrid KB search and `$semantic` inference work from the first load. `embed.py`
computes them with **`sentence-transformers/all-MiniLM-L6-v2` at revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`** (sentence-transformers 3.4.1,
torch 2.14.0 CPU), normalized and rounded to 4 decimals, so two runs give
byte-identical files. The held-out queue's query vectors ship with the app in
`src/data/support_incoming_vectors.json`, because the app does not run a model.
`load.py` refuses vectors made with any other model or revision. Measured on the
telco log (see `~/.tmp/handoff-coverage-probe/`, held-out set): `$semantic` improves
intent on paraphrased tickets (21/22 vs 18/22 token-only), but nearest similarity
alone does not cleanly separate paraphrases from off-topic text on templated data,
so the envelope shows it as information, not as a gate.

The **newest 300 tickets** (and their steps) are held out as the **incoming queue**:
never loaded, and committed at `src/data/support_incoming.json` for the app. The
envelope view predicts on those, so the tickets it is judged on were never loaded.
166 of the 300 repeat the exact wording of a loaded ticket (the fixture is written
from templates); results/novel_text.json re-scores every arm on the other 134.
The measurements below are over all 12,000.

## Planted causes, and what they measure

`python3 lifts.py` measures each effect from the written files only (plus the
replayed Northwind rows), never from the generator's internals. Numbers for the
default seed; "differs" means the 95% Wilson intervals don't overlap.

| story | planted | measured |
|---|---|---|
| who wrote | a known contact 92% of the time; otherwise a new address at the account's own domain | every one of the 240 domains names exactly one account, so the account is a lookup |
| category from the contact's role | finance writes about billing, developers about integrations | billing 0.34 of finance's tickets vs 0.04 of others'; integration 0.38 of developers' vs 0.15 (both differ) |
| an account's recurring issue | 30% of an account's tickets are its own recurring problem | an account's top issue is 0.38 of its tickets, vs 0.15 for the most common issue overall |
| product | from the account's own products, and named in the text | named in 81% of tickets |
| category from words | topic phrases share vocabulary; 10% of tickets mix two topics | 0 of 172 common words is a perfect rule; "invoice" 0.55, "report" 0.39 |
| priority | the desk's triage rules, followed 90% of the time: urgency words, or a bug on an Enterprise plan, are high; how-to questions are low | high 0.89 with urgency words, 0.89 for an Enterprise bug, 0.05 otherwise; how-to low 0.90 |
| drift | from 2026-07, 80% of `login` issues are fixed by `sso_reconnect`, not `reset_password` | `sso_reconnect` on login issues: 0.00 before, 0.79 after; on all access tickets: 0.00 before, 0.35 after |
| next step | each resolution is a step sequence ending in `done`, with 15% detours | e.g. how-to `identify_need → send_article` 0.84; every path's last step → `done` 1.00 |
| detractor risk | the same issue back within 30 days, first response >24h, a Red account | base 0.24; same issue back 0.34, >24h 0.34, Red 0.34 (Green 0.19); each differs from the base |
| recovery lever | assigned at random, so its effect is causal; the best action depends on size | detractor rate, best vs none: SMB credit 0.14 vs 0.24; Mid-market callback 0.11 vs 0.27; Enterprise CSM outreach 0.18 vs 0.33 (each differs) |
| upsell | offered at random on 30% of tickets from accounts that haven't churned | accepted 0.34 at `adoption_band` high vs 0.11 at low; Red accounts 0.04 (base 0.22) |
| **control** | the ticket `channel` has **no** effect on `nps_after` | each channel against the rest: \|z\| < 1.96 (email −1.53, chat −0.90, portal 1.60, phone 0.82); lift 0.96 to 1.04 |

The control is what makes the rest believable. `tests/test_support_fixture.py` fails
if it stops being null, and it also plants a +0.07 chat effect (`control_leak`) to
prove the check then fails.

## How learnable each step is

An **offline stand-in** (a naive-Bayes classifier over the same fields, trained on the
oldest 80% of tickets and tested on the newest 20%) shows which steps are decisions
history can make and which are genuinely uncertain outcomes. These are **not Aito's
numbers**; those come from a recorded run once the fixture is loaded.

| step | accuracy | top 3 | majority baseline | right when p ≥ 0.85 |
|---|---|---|---|---|
| account (sender domain) | 1.00 | | 0.01 | |
| product (text, account) | 0.84 | 0.95 | 0.15 | 0.93 |
| category (text) | 0.95 | 1.00 | 0.22 | 0.96 |
| priority (text, category, plan) | 0.77 | | 0.64 | 0.85 |
| resolution (text, month) | 0.91 | 1.00 | 0.16 | 0.94 |
| first step (text) | 0.95 | 1.00 | 0.40 | 0.96 |
| detractor after the ticket | 0.45 | | 0.40 | |
| upsell accepted | 0.78 | | 0.78 | |

So a view shows the first group as decisions (right or wrong against what happened),
and the last two as **risks**: a probability against the base rate, judged across the
queue, never as right or wrong on one ticket.

## Inputs and targets: what a demo may use to predict what

Some columns are recorded *after* the thing a demo would predict, or give it away.
Using them as inputs would make a prediction look better than it is:

| to predict | do not use as an input | why |
|---|---|---|
| `category`, `resolution` | `resolution`, `kb_article`, `kb_article.resolution`, `issue` | the article is the resolution's article; the resolution and the issue determine the category |
| `priority` | `first_response` | response time follows priority |
| `nps_after` | `csat_band` | both are recorded after the ticket; csat is derived from the NPS answer |
| `upsell_accepted` | (filter to `upsell_offered = yes`) | `upsell_accepted` is empty when no offer was made |
| the next step | `ticket.resolution`, `ticket.kb_article` | the resolution picks the path; use `ticket.issue` and `category` |

Also true of this data, and worth saying in any view built on it:

- **The text is templated.** No single word decides the category, but each opening
  clause belongs to exactly one category, so an LLM or a nearest-neighbour match reads
  the category off it easily. The cache story here is cost and speed, not that the
  LLM gets category wrong.
- **The account is a lookup**, not a prediction: the sender is a known contact, or a
  new address at a domain that names one account.
- Tickets from customers that later churned are included; upsells are never offered
  to them.

## Use

```bash
python3 scripts/support_fixture/generate.py            # writes data/ and src/data/support_incoming.json (byte-identical every run)
python3 scripts/support_fixture/lifts.py               # measure the planted effects
telco-tool-routing-bench/run-py scripts/support_fixture/embed.py   # the pinned vectors (sentence-transformers)
uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py           # dry run: prints the plan
uv run --with 'aitoai>=1.0' python scripts/support_fixture/load.py --apply   # writes (Antti runs it)
```

`load.py` writes only to a branch environment (default `support`), branched off
master so it keeps `customers` and `products` for the links. It only ever creates,
drops or fills the four support collections, refuses master, refuses an existing
environment unless `--reload` is given, and checks that every linked customer and
product exists and every ticket and article has its pinned vector before writing.
