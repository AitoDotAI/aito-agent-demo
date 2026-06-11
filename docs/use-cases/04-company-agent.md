# 4 · Company AI agent

**Domain:** Northwind Cloud · **Surface:** `Company → Company AI agent`
(+ `Toolbox`) · **Shape:** a `gpt-5-mini` chat loop over the linked 360
data

The [360 Dashboard](03-company-360-dashboard.md) drives the KPI ops from a
form. This surface hands them to an LLM as tools — a generic "talk to your
company's numbers" assistant that can act and learn to optimise outcomes,
not just report them.

## The toolbox

| Tool | Aito op | Returns |
|------|---------|---------|
| `kpi_snapshot` | `_predict` ×6 | conversion / churn / NPS / CSAT / adoption / on-time for a segment |
| `optimize_kpi` | `_predict $why` + `_recommend` | the lever that moves a chosen KPI + projected lift |
| `customer_360` | `_query` (linked) | one customer joined across deals, tickets, usage, invoices, feedback |
| `find_examples` | `_query` any domain | example rows + ids to ground a claim |
| `estimate_mrr` | `_estimate mrr_eur` | expected € / month for a segment |
| `launch_play` | **gated action** | drafts a play (e.g. an Exec-sponsor CSM motion) for approval — never runs |

Five are Aito reads over the linked Northwind data; the sixth only ever
drafts. Tool schemas: `GET /api/company-agent/tools`; loop in
`src/company_agent.py` over `src/agent_core.py`.

## What it can do that a BI bot can't

Ask *"Why are we losing Enterprise Pro accounts and what should we do?"*
and the agent calls `optimize_kpi("churn", {size:"Enterprise",
plan:"Pro"})`, which runs the `_predict $why` + `_recommend` pair from the
dashboard and returns the root cause **and** the counterfactual lever with
its lift — e.g. *"churn 35% → 22% via Exec-sponsor CSM."* Then it can draft
the play with `launch_play` (gated). A text-to-SQL bot can report the 35%;
it cannot prescribe the lever with calibration.

## The on/off A/B

Like the [Sales agent](02-sales-agent.md), the **Toolbox** view toggles
the Aito tools. Off, the agent has to guess the KPIs and levers — and says
so. On, every number is a live op over the linked data.

## How the UI renders it

Streamed chat with a trace card per tool call (op + `where` + result);
`customer_360` renders the joined record across domains; `launch_play`
renders behind a confirm-gate. Same strip as the sales agent (Aito
ON/OFF, tool/call counts).

## Out of scope

- No autonomous execution — `launch_play` drafts; a human runs it.
- The 360 join is read-only; the agent doesn't write to any domain table.
- "Learning" means Aito reflecting newly-logged outcomes on the next
  query — there is no fine-tuning and no per-chat memory.
</content>
