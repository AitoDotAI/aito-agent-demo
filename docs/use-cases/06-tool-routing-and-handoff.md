# 6 · Tool routing (short-list) + human handoff

**Domain:** Sonipra Telecom · **Surfaces:** `Support → Tool routing ·
short-list` and `Support → Human handoff` · **Ops:** `_predict`
short-list · `$p` gate

Two faces of the same idea: a calibrated `_predict` makes an LLM agent
cheaper (by narrowing its choices) and safer (by deciding who acts).

## Tool routing — Aito augments the LLM, it doesn't replace it

An agent with a 240-tool catalog weighs all 240 on every ticket — a big
prompt, every time. `_predict` over the `tool_calls` table reads the
ticket text and hands back the ~5 tools history says are relevant, so the
LLM picks from 5, not 240.

```jsonc
POST /api/v1/_predict
{
  "from": "tool_calls",
  "where": { "text": "My screen is cracked, the glass is shattered. Help?" },
  "predict": "tool",
  "select": ["$p", "feature"],
  "limit": 5
}
// → a 5-tool short-list, ranked by calibrated probability
```

Same answer, **~16× fewer tokens**, lower latency — and when Aito is
confident enough, the LLM isn't needed at all. Backend: `GET /api/route`
in `src/app.py` runs the LLM over the full catalog and over Aito's
short-list, so the UI can show the token/latency gap directly. The view
makes the augment thesis literal: *the same model, two ways*.

## Human handoff — calibrated confidence as governance

The same `_predict` `$p` is the routing decision for *who acts*:

| Confidence | Action |
|------------|--------|
| `$p ≥ 0.85` | auto-resolve |
| `0.65 ≤ $p < 0.85` | hand to a human with the tentative read attached |
| `$p < 0.65` | escalate — too ambiguous to auto-act |
| any sensitive intent (`refund`, `cancel`) | gated regardless of `$p` |

A confident prediction is allowed to act; a borderline one becomes a
human's decision *with Aito's best guess attached* (faster triage, not a
blank queue); anything that moves money is gated no matter how confident.
The number decides — that's governance you can't get from an LLM that only
ever asserts. Backend: `GET /api/handoff` predicts intent across the queue
and buckets each item by `$p`; the sidebar badge shows the handoff count.

## How the UI renders it

**Tool routing** shows the catalog size, the Aito short-list with
probabilities, and the LLM's pick over the full catalog vs. the short-list
— with the token/latency/confidence deltas. **Human handoff** shows the
queue bucketed into auto / assist / escalate, each item carrying its
predicted intent and `$p`.

## Out of scope

- The 240-tool catalog and `tool_calls` rows are synthetic (seeded by
  `scripts/seed_routing.py` from the routing benchmark) — the point is the
  short-listing mechanics, not a real tool registry.
- Handoff buckets the queue; it doesn't implement the downstream
  human-review workflow.
</content>
