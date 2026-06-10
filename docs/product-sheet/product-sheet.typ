// Aito Predictive Agent — Product Sheet
// Compile: ./do product-sheet   (or: nix-shell -p typst --run \
//   "typst compile --root . docs/product-sheet/product-sheet.typ docs/product-sheet/product-sheet.pdf")

#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2.3cm),
  footer: context [
    #set text(8pt, fill: luma(150))
    #h(1fr) Aito Predictive Agent · agent.aito.ai · Apache 2.0 #h(1fr)
    #counter(page).display()
  ],
)

#set text(size: 10pt, fill: luma(30))
#set par(justify: true)
#show heading.where(level: 1): set text(size: 18pt, weight: 700)
#show heading.where(level: 2): set text(size: 13pt, weight: 600)
#show raw: set text(font: "DejaVu Sans Mono", size: 8.5pt)

#let teal   = rgb("#12B5AD")
#let purple = rgb("#9B69FF")
#let gold   = rgb("#E0B34D")
#let indigo = rgb("#0c0f41")
#let muted  = luma(120)

#let shot(name) = image("shots/" + name + ".png", width: 100%)

#let feature(title, description, icon: none) = box(
  width: 100%, inset: 11pt, radius: 6pt, stroke: luma(220),
  [
    #if icon != none { text(size: 13pt, icon + "  ") }
    #text(weight: 600, size: 10.5pt, title) \
    #text(size: 9pt, fill: luma(80), description)
  ],
)

#let op(name, what) = [
  #text(weight: 600, fill: teal, raw(name)) — #text(size: 9.5pt, fill: luma(70), what) \
]

// ───────────────────────────── Cover ─────────────────────────────
#v(0.6cm)
#align(center)[
  #text(size: 12pt, fill: muted, weight: 500)[Aito.ai · The Predictive Database for Agents]
  #v(0.25cm)
  #text(size: 29pt, weight: 700, fill: luma(20))[The faculty your agent is missing]
  #v(0.15cm)
  #text(size: 15pt, fill: luma(60), weight: 500)[
    LLMs gave your agent reasoning. RAG gave it memory. \
    Aito gives it #text(fill: teal, weight: 600)[intuition].
  ]
  #v(0.35cm)
  #text(size: 10pt, fill: luma(80))[
    A live agent that calls Aito ops as tools — grounded numbers it can't invent,
    and the action that wins. Three working surfaces (sales, company 360, support),
    one predictive database, no model training. Better, faster, cheaper —
    and higher-yield.
  ]
  #v(0.7cm)
  #shot("home")
]
#pagebreak()

// ─────────────────────────── Challenge ───────────────────────────
= Where a capable agent quietly falls down

None of these mean you picked the wrong model or built the wrong platform. They're
the predictable failure modes of asking one LLM to reason _and_ remember _and_ do
arithmetic over a large, structured, ever-changing dataset. Each has a one-query fix.

#v(0.3cm)
#grid(
  columns: (1fr, 1fr, 1fr), gutter: 10pt,
  feature("Tool / option sprawl", "Hundreds of tools or SKUs in context → selection degrades, prompts bloat.", icon: "🧰"),
  feature("An LLM call on every step", "Multi-step workflows take seconds and burn tokens, per ticket, at scale.", icon: "🐌"),
  feature("Vector search misfires", "Embeddings dilute identifiers — the nearest neighbour is the wrong customer.", icon: "🎯"),
)
#v(8pt)
#grid(
  columns: (1fr, 1fr, 1fr), gutter: 10pt,
  feature("Bad with numbers", "Aggregation, drivers, estimates — the model guesses, often confidently wrong.", icon: "🔢"),
  feature("No sense of \"how sure\"", "Overconfident output gives no signal for when to act vs ask a human.", icon: "⚖️"),
  feature("Amnesiac about your data", "It knows the internet, not your customers — and you can't feasibly train it on them.", icon: "🧠"),
)

#v(0.7cm)
= The solution: Aito is a tool in the agent's toolbox

Aito is a predictive database. Load your history; query for predictions,
recommendations and statistics through SQL-like calls. *No model training, no
retraining schedule, no MLOps.* Every answer carries a calibrated probability
(`$p`) and an explanation (`$why`) that traces straight to your data.

The agent keeps doing the reasoning and the talking. When it needs a number it
can't invent — win odds, effort, churn, the action that wins — it *calls an Aito
op as a function.* The same agent with the Aito tools switched off has to guess,
and says so. That is the whole pitch, A/B in one toggle.

#v(0.3cm)
#grid(
  columns: (0.95fr, 1.05fr), gutter: 16pt,
  box(width: 100%, inset: 12pt, radius: 6pt, fill: luma(247))[
    #op("_predict", "a class + calibrated \$p + \$why")
    #op("_match", "the relevant memory, by structure")
    #op("_relate", "drivers / lift behind a number")
    #op("_estimate", "a number, from history")
    #op("_recommend", "the next action that maximises a goal")
  ],
  [
    *One query, any language.* Call it like a tool or an MCP endpoint from any agent
    framework. Your platform stays the brain; Aito is the instant, calibrated memory
    underneath it.

    *Zero MLOps.* No model files, no retrain, no drift. A row added today is in the
    next prediction — which is also how the agent _learns_: log an outcome and the
    very next recommendation is sharper.

    *Calibrated & explainable.* Every answer has a `$p` and a `$why`. Auditable by
    design — the `$p` is a governance gate: auto when sure, escalate when not.
  ],
)
#pagebreak()

// ─────────────────────── Agent 1: Sales ───────────────────────
= Aito in the toolbox — the sales agent

A live gpt-5-mini chat loop. Ask it about a deal; it reasons, then calls Aito ops
for the numbers it can't invent: win-odds (`_predict` + `$why`), effort
(`_estimate`), reference projects (`_query`), and the outreach that books the most
meetings (`_recommend`) — quoting the *lift over the unoptimised baseline*. Every
tool call is rendered inline, so you watch Aito work inside the agent. Money/state
actions are gated: it drafts the email, it never sends.

#v(0.3cm)
#shot("sales-agent")
#v(6pt)
#text(size: 9pt, fill: muted)[
  Toolbox on/off · grounded numbers vs flagged guesses · 4 Aito calls in ~0.8 s,
  \$0 · the LLM call reasons; Aito supplies the facts.
]

#v(0.6cm)
// ─────────────────────── Agent 2: Company 360 ───────────────────────
= A 360° copilot that optimises KPIs — the company agent

One linked `customers` master joined to sales, support, product, finance and CX.
A SQL+LLM BI bot can `COUNT(*)`; this copilot calls Aito for the *360 KPI snapshot*
(conversion, churn, NPS, CSAT, adoption, on-time revenue), the *single lever that
moves each one* with the projected lift, and a *customer-360 join* across every
domain. It doesn't just report — it optimises, drafts the play (gated), and learns:
Aito has no training step, so a logged outcome sharpens the next prediction.

#v(0.3cm)
#shot("company-360")
#v(6pt)
#text(size: 9pt, fill: muted)[
  "Churn 40% → 25% via an Exec-sponsor CSM motion" — driver, lever and projected
  lift, computed live from the company's own linked data. See · optimise · act · learn.
]
#pagebreak()

// ─────────────────────── The 360 Dashboard — causal analysis ───────────────────────
= The 360 Dashboard — every KPI, diagnosed and prescribed

The same ops, called *directly* (no agent) as a data view. Pick a customer segment
and each KPI shows three things, each with a "?" that opens the live explanation —
the per-prediction `$why` pattern used across the Aito demos:

#v(0.3cm)
#grid(
  columns: (1fr, 1fr, 1fr), gutter: 12pt,
  feature("Why the rate is the rate", "_predict $why: the base rate scaled by each segment attribute's lift — e.g. conversion base 40% × SMB ×1.11 × Free ×0.92.", icon: "🔢"),
  feature("Root causes", "_relate scoped to the segment ($on): within SMB·Free, Red-health customers churn 44% vs 28% → ×1.39. Drivers (>1) and protective factors (<1).", icon: "🔬"),
  feature("Levers + projected lift", "_recommend ranks the actionable lever; the recommendation differs by segment (SMB → Guided trial, Enterprise → CSM-led) and projects the result.", icon: "🎚️"),
)

#v(0.3cm)
#shot("dashboard")
#v(6pt)
#text(size: 9pt, fill: muted)[
  Diagnosis (`_relate`) and prescription (`_recommend`) on every KPI, each explained
  by a live `$why` — the predictive database as a closed optimise-act-learn loop.
]
#pagebreak()

// ─────────────────────── Agent 3: Support ───────────────────────
= Predict-first support — the resolution console

The same ticket, two engines, side by side. An LLM agent reasons the resolution out
on every ticket — seconds and tokens. `aito._predict` reads the intent and the one
parameter it needs straight from history — two calls, sub-second, \$0, with a
calibrated `$why`. A confident hit is served instantly (a cache hit); a miss falls
through to the LLM, whose answer becomes the next cache entry. The `$p` gate routes
the unsure ones to a human, and anything sensitive (refund, cancel) is gated regardless.

#v(0.3cm)
#shot("console")

#v(0.7cm)
= Benchmarked, not asserted

Three failure modes every agent team hits — each run as a real benchmark (live Aito
+ live gpt-5-mini on seeded, realistic data) against the tool a good engineer would
otherwise reach for.

#v(0.3cm)
#grid(
  columns: (1fr, 1fr, 1fr), gutter: 10pt,
  feature("Shortlisting holds at scale", "Embedding-retrieval shortlist degrades as the catalog grows; Aito holds and hands the LLM ~16× fewer tokens for the same pick.", icon: "01"),
  feature("~9–10× lower latency", "A 6-step LLM resolution chains to ≈22 s; Aito predicts in parallel in ~0.15 s — resolved before the agent clears step one.", icon: "02"),
  feature("Right context-memory", "Vector search picks the wrong customer's memory 86% of the time; Aito conditions on structure and recovers what the text can't identify.", icon: "03"),
)

#v(0.8cm)
#align(center)[
  #box(width: 100%, inset: 16pt, radius: 8pt, fill: indigo)[
    #set text(fill: white)
    #text(size: 15pt, weight: 700)[See it just know — all three agents, live.]
    #v(4pt)
    #text(size: 10.5pt, fill: rgb("#c7cdf2"))[
      Real predictions, real latency, real cost — at #text(fill: teal, weight: 600)[agent.aito.ai].
      A primitive your agents call, not another platform to adopt.
    ]
  ]
]
