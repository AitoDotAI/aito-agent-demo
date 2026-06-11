# 5 · Ticket resolution — same ticket, two engines

**Domain:** Sonipra Telecom · **Surface:** `Support → Ticket resolution`
· **Ops:** `_predict` ×2 vs a live `gpt-5-mini` call

A support ticket arrives. The view resolves it **two ways at once**, side
by side: a live LLM agent reasons the answer out (seconds, tokens, a
dollar cost), while Aito reads the answer straight from 4,000 past
`resolutions` (two `_predict` calls, sub-second, $0, with a calibrated
`$why`). The point is the gap.

## The data

`resolutions` columns: `text` (the ticket, English-analysed),
`sender_domain`, `intent` (the action to take), plus the parameter fields
`location`, `target_service`, `kb_article`. Each historical row is one
resolved ticket.

## The queries

**Intent** — what should happen — predicted from the ticket text and who
sent it:

```jsonc
POST /api/v1/_predict
{
  "from": "resolutions",
  "where": {
    "text": "Is there a network outage? Nothing works in Helsinki.",
    "sender_domain": "alerts.monitoring.io"
  },
  "predict": "intent",
  "select": ["$p", "$why"]
}
// → check_outage  (p ≈ .9)  with the words/sender that drove it
```

**Parameter** — the one slot the action needs (e.g. `location` for an
outage check) — a second `_predict` conditioned the same way. Two calls,
no chain, no agent loop. Backend: `GET /api/resolve` (Aito) and `GET
/api/resolve-llm` (the live baseline) in `src/app.py`.

## How the UI renders it

Two columns race in real time. The **LLM** column streams a "reasoning…"
state, then shows the resolved action, token count, latency, and dollar
cost — and a note that it asserts without calibrated confidence or
evidence. The **Aito** column shows the predicted intent + parameter as
`PredictionBadge`s with confidence bars, the `$why` cards (verifiable from
history), and `0 model calls · $0`. A KPI strip across the top shows Aito
latency, LLM latency, the **speed-up** (often 100×+), and LLM cost per
resolution vs Aito's $0.

## The framing: a predictive cache in front of the LLM

Aito isn't competing with the LLM here — it's a **cache that learned**. A
confident hit fires instantly and free; a miss falls through to the LLM,
whose answer becomes the next row Aito learns from. Sensitive intents
(`refund`, `cancel_service`) are gated regardless of confidence — see
[06-tool-routing-and-handoff.md](06-tool-routing-and-handoff.md).

## Out of scope

- Aito resolves intent + parameter; it does not *execute* the action
  (that's the gated/handoff path).
- LLM latency and cost vary with provider load — the numbers are live, so
  they move between runs.
</content>
