# 2 · Sales agent (Aito in the toolbox)

**Domain:** Northlight · **Surface:** `Sales → Sales agent` (+ `Toolbox`)
· **Shape:** a `gpt-5-mini` chat loop whose tools are Aito ops

The [Opportunity Assistant](01-opportunity-assistant.md) calls the four
ops *directly* from a form. This surface hands the same ops to an LLM as
**tools** and lets it decide when to call them. The agent is a plain
chat loop — what makes it useful is what's in its toolbox.

## The toolbox

| Tool | Aito op | Returns |
|------|---------|---------|
| `win_odds` | `_predict outcome` | `$p(won)` + `$why` drivers |
| `estimate_effort` | `_estimate effort_days` | person-days |
| `find_references` | `_query where outcome=won` | example briefs |
| `recommend_outreach` | `_recommend` toward `meeting=yes` | channel + angle + lift |
| `propose_send_email` | **gated action** | drafts an email for human approval — never sends |

Four are Aito reads over Northlight's history; the fifth is an action
that only ever produces a **draft**. Tool schemas: `GET
/api/sales-agent/tools`; the loop is `src/sales_agent.py` over the shared
`src/agent_core.py`.

## It optimises, not just informs

Ask *"Warm referral into an Enterprise SaaS company that wants a data
platform build, sole-source — should we pursue it, and how big is the
job?"* and the agent calls `win_odds` + `estimate_effort`, then quotes
the calibrated numbers back. Ask it to *get a meeting* and it calls
`recommend_outreach`, which returns the angle that maximises `meeting =
yes` **and the lift** over the default approach — e.g. *"Warm intro +
Case study: 59% vs 16% → 3.7× more meetings."* That lift is a live
`_recommend` result, not a model assertion.

## The on/off A/B (the augment thesis in one switch)

The **Toolbox** view toggles each Aito tool. Turn them off and ask the
same question: the agent has no grounded numbers to call, so it **guesses
— and flags that it's guessing**. Turn them back on and the same prompt
returns calibrated `$p`, real effort, real lift. That switch is the whole
argument: the LLM brings the reasoning and the words; Aito brings the
intuition it can't invent.

## How the UI renders it

The chat streams the agent's turns; each tool call renders as a trace
card showing the op, the `where`, and the returned numbers. Gated actions
(`propose_send_email`) render behind a send-gate the user must confirm —
the agent can draft but not dispatch. A strip shows Aito ON/OFF, tool
count, Aito-call count, and the "better · faster · cheaper · +higher-yield"
axes.

## Out of scope

- No autonomous sending or CRM mutation — every state-changing action is
  a draft behind a human gate.
- The agent reasons over what the tools return; it does not fine-tune or
  persist anything between sessions (Aito learns from *logged outcomes*,
  not from the chat).
</content>
