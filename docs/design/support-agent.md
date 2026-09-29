# Design: one support agent inside Aito's predictive envelope

**Status:** proposal (2026-09-28). The CPO lane agrees the scope and ordering below; the three
decisions at the end are with Antti. Nothing here is built yet.

## The idea

Today the demo shows Aito's agent techniques as separate pages over three unrelated datasets
(telco tickets, Northwind accounts, Northlight sales). Antti's direction: **one agentic support
system** where a ticket flows through the steps a real support agent takes, and every step shows
the Aito op that grounds, speeds or decides it. The LLM stays in the middle (it reads, writes and
reasons); Aito is the **predictive envelope** around it.

It should demonstrate the agentic toolbox against three goals:

1. **Cost and speed**: fewer and cheaper LLM calls, answers in milliseconds where history decides.
2. **Impact**: better outcomes for the customer and the business (CSAT, NPS, retention, revenue).
3. **Analytics and governance**: every decision logged with its `$p` and `$why`, rules reviewable,
   drift visible.

## One ticket, step by step

| Step | What the agent needs | Aito op | Goal |
|---|---|---|---|
| 1. Intake | Who is this? Which product, category, priority? | `_predict` customer (from sender + text), product, category, priority | speed, governance |
| 2. Context | The customer's account, open issues, usage, NPS, value | `_query` with `$refs` (the 360 neighbourhood, built in PR #13) | impact |
| 3. Decide or ask | Is this a repeated decision history already answers? | decision cache: `_predict` resolution at `$p ≥ τ`, else the LLM (use case #3) | cost, speed |
| 4. Narrow | Which tools / KB articles apply? | `_predict` shortlist (built); hybrid KB search `$nearest` + `$match` (use case #1) | cost |
| 5. Similar cases | How were tickets like this solved, and did it work? | `_match` / similarity on text, filtered by outcome | impact |
| 6. Next step | Multi-step fixes: what comes after this step? | `_predict` next action given the ticket and the steps so far | speed |
| 7. Protect the relationship | Will this customer turn detractor? What prevents it? | `_predict` NPS / churn risk after this ticket; `_recommend` the action that maximises a good outcome | impact |
| 8. Grow | Is there a fitting next product for this account? | `_recommend` / link prediction on products, gated to healthy accounts | impact |
| 9. Hand off | Who acts: auto, assist, or a human? | the `$p` gate (built: handoff queue) | governance |
| 10. Learn and govern | Log the decision; review the rules decisions follow; watch drift | log rows with a timestamp; `_relate` / `$patterns` rules (PR #14); per-τ accuracy | governance, analytics |

**The view:** the ticket in the centre, the LLM agent's conversation in one column, and the envelope
around it: one card per step with the op, `$p`, `$why`, latency, and "LLM calls saved". An Aito
on/off toggle replays the same ticket LLM-only, so the three goals show as measured differences, not
claims. The toggle's "calls saved" and latency numbers come from **recorded runs**, labelled as such
with their date and engine build, never estimated.

## The data this needs, honestly

No current dataset can carry it. Telco tickets have text but no customer links; Northwind's linked
tickets have no text. Composing the two in the UI would fake a connection that isn't in the data.

**Proposal: one new fixture, `support`, linked to the existing Northwind customers and products**,
generated like the graph sandbox (aito-demo #43): synthetic, labelled as synthetic, with **planted,
measured causes**, and a `lifts.py` that measures each effect from the written files before loading:

- `support_tickets`: text, sender, `customer → customers`, `product → products`, category, priority,
  channel, resolution, kb_article, `created_at`, `csat_band`, `nps_after`.
- `support_steps`: `ticket →`, step number, action, previous action, outcome, `created_at`.
- `kb_articles`: title, body, product (plus an offline embedding vector for hybrid search).

Planted effects (each measured, so a view can claim only what the data holds):

- priority from plan, size and urgency words; category from text;
- the next step from the previous step and category (a real sequence, not independent rows);
- detractor risk rises with repeat tickets, slow first response and the account's health, and falls
  with the recommended recovery action (so `_recommend` has a real lever);
- upsell fit from adoption and plan (a real, modest effect, never on at-risk accounts);
- a planted **drift**: one category's resolution changes after a date, so the drift view has
  something true to find.

Adding tables doesn't change any existing table, so the published /company numbers stay as they are.

## What already exists and gets reused

The resolution console and `$p` gate, the tool shortlist, the handoff queue, the 360 `$refs`
neighbourhood (PR #13), the rules review (PR #14), the agent guards against invented inputs and
figures (PR #11), and the shared agent loop (`src/agent_core.py`).

## The LLM's half: the reply, and tickets Aito doesn't know

Built on phase 1 (src/support_reply.py, the Reply panel on the Support agent page). Aito decides;
the LLM writes. The recorded comparison (scripts/support_fixture/compare_modes.py) found the LLM adds
little to the structured decisions, so it is used where Aito can't help:

- **Routine** (Aito's resolution passed its gate): gpt-5-mini writes the reply from the decided
  facts only, and first says whether the ticket's own words support them. That check is the second
  opinion on Aito's known overconfidence on off-topic and vague text.
- **Unfamiliar** (Aito unsure, or the writer said the facts don't fit): the LLM reads the ticket with
  Aito's shortlists and the account's similar past tickets, says what the customer wants, picks an
  allowed resolution or none, and drafts for a person. Never sent automatically. A button asks
  gpt-6-luna for a closer read; it took 58 to 100 s per call when measured on 2026-09-29, so it is
  not the default.
- **Guards, in code:** no refund, credit or discount the decisions don't include; no figure the
  facts don't contain; no article but the decided one; anything that moves money goes to a person.
- **Your own words:** the page can run the envelope on edited text from the same sender (no truth,
  nothing scored), which is how a visitor sees an unfamiliar ticket handled.

**Hardening for a public page:** the reply route has its own per-IP limit (6 a minute), a daily
LLM token budget for all visitors together (past it, drafting pauses and Aito's decisions stand), a
600-character cap on visitor text, and the ticket fenced as data. A ticket that tries to instruct the
AI is never auto-sent, on either of two reads: a pattern in code, or the writer's own flag. The
gpt-6-luna read has a hard 120 s limit with a visible wait and a cancel. An Aito error on one step
blanks that step (the engine's mergeSampleFreqs 500, td-20260929182755894024) instead of failing the
ticket; more than half the steps failing is reported as Aito being down.

**The sanity set** (scripts/support_fixture/reply_probes.py, live, 2026-09-29): unfamiliar, vague and
injection tickets that must never be auto-sent, each run from two real senders, plus 20 real
held-out tickets.

| run | tuning probes (26) | held-out probes (20) | real tickets Aito was sure of, auto-sent |
|---|---|---|---|
| first, before any fix | 21 ok, 3 auto-sent, 2 engine errors | not yet written | 15 of 15 |
| after fixing on the tuning set (**the honest held-out number**) | 25 ok, 1 auto-sent | **17 ok, 3 auto-sent** | 15 of 15 |
| after a further prompt fix (tuned on both; not an independent number) | 25 ok, 1 auto-sent | 18 ok, 2 auto-sent | 14 of 15 |

What still gets through: "Hello, can someone call me?" and "Where can I buy a Northwind hoodie?". Aito's
gate reads both as sure, and gpt-5-mini accepts the decided resolution as an answer, once inventing
that the article holds a store link. Prompting has stopped helping here; the structural fix is the
engine's coverage measure (how much of a ticket's wording Aito has seen), which core-a is building,
and the page's caveat stays until it lands. Each held-out set is spent once looked at; the next honest
number needs a fresh one.

## Phasing

1. **Fixture and read-only envelope.** Generator plus `lifts.py`, loaded to a branch environment by
   Antti; steps 1, 2, 4, 5, 7, 9 as one page over it, with the LLM toggle. Needs: the load.
2. **Cache and learning.** Steps 3, 6 and 10 with writes (serve at `$p ≥ τ`, learn from each LLM
   answer, log with timestamps, drift). This is where use case #3's *demo* lives. Needs: a writable
   engine (the public v2 image) and the write model below.

   Use case #3's *benchmark* stays separate: banking77 (public), recorded offline runs, the per-τ
   served-accuracy curve as the calibration test, against an exact-match and an embedding cache. The
   headline claim must come from public data anyone can reproduce, not from this synthetic fixture.
   Its harness is built when the public v2 image lands, in parallel with phase 2.
3. **Growth and analytics.** Step 8, and the analytics side: per-τ served accuracy, cost saved,
   rules and drift over the log.

## Decisions needed

1. **The new fixture** (Antti): yes or no to a `support` fixture on shared, loaded by Antti to a
   branch environment first.
2. **Narrative** (Antti): does the unified support agent become the demo's lead story? Until phase 1
   is live, the telco pages stay as the "techniques" section; fold them in or not is decided then.
3. **Writes in the public demo** (phase 2): per-visitor sandbox, a shared resettable environment,
   or read-only replay. The CPO lane recommends the shared resettable environment with a scheduled
   restore (the accounting demo's hourly rule-restore pattern, ADR 0025): per-visitor sandboxes are
   much more machinery for little demo value.
