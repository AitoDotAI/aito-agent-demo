# Use-case library

One document per surface in the demo, mirroring the layout of the other
Aito reference demos. Each page covers: **what the feature does**, the
**exact Aito query** that produces it, **how the UI renders** the result,
and **what's deliberately out of scope**.

| # | Surface | Domain | Operator(s) | Doc |
|---|---------|--------|-------------|-----|
| 1 | Opportunity Assistant | Sales (Northlight) | `_predict` · `_estimate` · `_query` · `_recommend` | [01-opportunity-assistant.md](01-opportunity-assistant.md) |
| 2 | Sales agent (tools) | Sales (Northlight) | agent → 4 Aito tools + gated action | [02-sales-agent.md](02-sales-agent.md) |
| 3 | 360 Dashboard | Company (Northwind) | `_predict` · `_relate $on` · `_recommend` | [03-company-360-dashboard.md](03-company-360-dashboard.md) |
| 4 | Company AI agent | Company (Northwind) | agent → 5 Aito tools + gated play | [04-company-agent.md](04-company-agent.md) |
| 5 | Ticket resolution | Support (Sonipra) | `_predict` ×2 vs live LLM | [05-ticket-resolution.md](05-ticket-resolution.md) |
| 6 | Tool routing + handoff | Support (Sonipra) | `_predict` short-list · `$p` gate | [06-tool-routing-and-handoff.md](06-tool-routing-and-handoff.md) |

## The thesis in one line

An LLM agent reasons; **Aito gives it intuition** — calibrated, learned
from your own rows, queryable as one of five ops (`_predict`,
`_estimate`, `_recommend`, `_relate`, `_match`). The sales and company
surfaces show the agent *calling* those ops as tools; the support
surfaces show the same ops *replacing* or *narrowing* LLM calls for
speed, cost, and governance.

Every query below runs against the live, public, **read-only** instance
`https://shared.aito.ai/db/aito-agent-demo` (key in the
[root README](../../README.md#try-it-instantly-no-signup)). The schema is
viewable at `/api/schema` on the running app.

Back to the [project README](../../README.md).
</content>
