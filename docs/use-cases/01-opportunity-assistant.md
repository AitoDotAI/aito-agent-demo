# 1 · Opportunity Assistant

**Domain:** Northlight (a consulting firm) · **Surface:** `Sales →
Opportunity Assistant` · **Ops:** `_predict` · `_estimate` · `_query` ·
`_recommend`

A new opportunity comes in. The assistant builds a deal sheet from the
firm's own 1,800 past `engagements` and 2,200 `outreach` sends — four
numbers an LLM would otherwise have to invent, each a real Aito call.

## What it produces

| Block | Question | Op | Field |
|-------|----------|----|-------|
| **Win likelihood** | How likely is this to close? | `_predict` | `outcome` → `$p(won)` + `$why` |
| **Effort & business case** | How big is the job? | `_estimate` | `effort_days` (person-days) |
| **Reference projects** | What similar work have we won? | `_query` | rows where `outcome = "won"` |
| **Best way in** | Which outreach books the meeting? | `_recommend` | `angle` / `channel` toward `meeting = yes` |

## The queries

**Win odds** — condition on the deal's shape, predict the outcome with a
calibrated probability and the drivers behind it:

```jsonc
POST /api/v1/_predict
{
  "from": "engagements",
  "where": {
    "client_industry": "SaaS",
    "service_line": "Data Platform",
    "deal_size_band": "L",
    "lead_source": "Referral",
    "relationship": "Existing client"
  },
  "predict": "outcome",
  "select": ["$p", "feature", "$why"]
}
// → won ≈ 0.92  (Cold outbound instead of Referral drops it sharply)
```

**Effort** — the same shape, a numeric answer instead of a class:

```jsonc
POST /api/v1/_estimate
{
  "from": "engagements",
  "where": { "service_line": "Data Platform", "deal_size_band": "L",
             "complexity": "Medium", "team_seniority": "balanced" },
  "estimate": "effort_days"
}
```

**References** — the won deals that look like this one, for the proposal:

```jsonc
POST /api/v1/_query
{
  "from": "engagements",
  "where": { "service_line": "Data Platform", "outcome": "won" },
  "select": ["brief", "effort_days", "deal_size_band", "region"],
  "limit": 3
}
```

**Best way in** — `_recommend` ranks the values of `angle` that most
increase the probability of `meeting = yes` for this buyer. This is the
op that *optimises* rather than describes:

```jsonc
POST /api/v1/_recommend
{
  "from": "outreach",
  "where": { "target_industry": "SaaS", "target_role": "Head of Data" },
  "recommend": "angle",
  "goal": { "meeting": "yes" },
  "limit": 3
}
```

## How the UI renders it

The form across the top is the `where` clause — change industry, service
line, deal size, lead source, role, complexity, and every block
re-queries. Win odds shows the `$p` as a confidence bar with the `$why`
drivers underneath (`PredictionBadge` + `WhyCards`); the outreach block
shows the recommended angle with its **lift** over the un-optimised
baseline. Backend route: `GET /api/opportunity` in `src/app.py`, which
fans out to the four ops via `AitoClient`.

## Out of scope

- No CRM write-back — the assistant reads history and proposes; it never
  mutates a deal record.
- Effort is a point estimate from comparable history, not a bottom-up
  resourcing plan.

See also: [02-sales-agent.md](02-sales-agent.md) — the same four numbers,
but called by an LLM as tools in a chat.
</content>
