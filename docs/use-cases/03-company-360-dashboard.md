# 3 · 360 Dashboard

**Domain:** Northwind Cloud (a SaaS company) · **Surface:** `Company → 360
Dashboard` · **Ops:** `_predict` · `_relate $on` · `_recommend`

The 360 model is one `customers` master (1,500 rows) linked to five child
tables — `deals`, `tickets`, `feedback`, `usage`, `invoices`. Because
`customers.customer_id` is a foreign key on every child, you can condition
a child-table query on a *customer attribute* (`customer.size`,
`customer.plan`) and Aito traverses the link. No join to write.

Pick a segment (industry · size · plan) and the dashboard renders six
KPIs, each fully diagnosed: the **rate**, its **root causes**, the
**lever** that moves it, and a `$why` on every number.

## The six KPIs

| KPI | Table | Target → good | Lever (`_recommend`) |
|-----|-------|---------------|----------------------|
| Conversion | `deals` | `converted = yes` | `nurture_track` |
| Churn | `customers` | `churned = no` | `csm_motion` |
| NPS | `feedback` | `score_band = promoter` | `theme` |
| CSAT | `tickets` | `csat_band = good` | `channel` |
| Adoption | `usage` | `active = yes` | `onboarding_push` |
| On-time | `invoices` | `status = paid` | `term` |

The lever's *effect varies by segment* — `csm_motion = Exec-sponsor`
barely moves an SMB but strongly retains an Enterprise account. The seed
data encodes those interactions on purpose, so changing the segment
genuinely changes the recommendation.

## Three queries per KPI

**1 · The rate + its `$why`** — predict the outcome for the segment and
read the segment-attribute drivers behind the base rate:

```jsonc
POST /api/v1/_predict
{
  "from": "customers",
  "where": { "size": "Enterprise", "plan": "Pro" },
  "predict": "churned",
  "select": ["$p", "$why"]
}
```

**2 · Root causes — `_relate` scoped with `$on`.** The subtlety: a plain
`_relate` to `churned` mixes the whole population. To find what drives
churn *within this segment*, scope it. `$on` takes exactly two
propositions — the outcome and the segment — so multi-condition segments
go inside an `$and`:

```jsonc
POST /api/v1/_relate
{
  "from": "customers",
  "relate": { "$on": [
    { "churned": "yes" },
    { "$and": [ { "size": "Enterprise" }, { "plan": "Pro" } ] }
  ] }
}
// → drivers ranked by within-segment lift:
//   health = Red        (rate with vs without)
//   onboarding = None
//   nps_band = detractor
```

This is the difference between "Red-health customers churn a lot" (true
everywhere) and "*within Enterprise Pro*, Red health is the thing pushing
this segment's churn" — the second is actionable.

**3 · The lever — `_recommend`.** Rank the values of the lever field that
most increase the *good* outcome for the segment:

```jsonc
POST /api/v1/_recommend
{
  "from": "customers",
  "where": { "size": "Enterprise", "plan": "Pro" },
  "recommend": "csm_motion",
  "goal": { "churned": "no" },
  "limit": 4
}
// → Exec-sponsor (highest retention) ... None (lowest), each with $p
//   the UI shows the lift = p(best) / p(current)
```

Backend: `GET /api/company-360` in `src/app.py` iterates a `_KPIS`
registry, calling `_predict` (rate + `$why`), `_relate_drivers` (causes
via `relate_on`), and `_recommend` (lever) per KPI, plus a spotlight
customer joined across every domain via `_query`.

## How the UI renders it

Each KPI is a card: the rate as a big number with a `?` that opens its
`$why` (base rate × segment lifts), then **three root causes** and **three
recommended levers**, each row with its own `?` explaining that row —
causes show a with/without comparison; levers show the projected lift.
This is the calibrated-confidence + `$why` pattern the other Aito demos
use, applied to causal KPI analysis.

## Why this beats a SQL+LLM BI bot

A text-to-SQL bot can `COUNT(*)` the churn rate. It cannot tell you, with
calibration, *which lever to pull and how much it will move the number* —
that needs `_relate` for causes and `_recommend` for the counterfactual,
both learned from history with no model to train. And because Aito has no
training step, a logged outcome sharpens the next prediction: a closed
loop, no retrain.

## Out of scope

- No write path — the dashboard reads and prescribes; acting on a lever is
  the [Company agent's](04-company-agent.md) gated `launch_play`.
- KPI rates are conditional probabilities from history, not a financial
  forecast.

See also: [04-company-agent.md](04-company-agent.md) — the same ops in a
chat.
</content>
