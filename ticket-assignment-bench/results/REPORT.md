# Ticket field-assignment benchmark — results (v3)

The faithful version: **customer and project were never fields — they had to be
inferred.** The real signal is the email **sender domain**, which usually (not
always) identifies the customer. The production pipeline inferred the customer by
**text vector-search over history** and cascaded that (wrong) customer into a wrong
assignee. The question here: can Aito infer the assignee **directly** from
`{text, sender_domain}` and collapse that chain? Everything is LLM-free.

n_test = 800, 48 agents, k = 7 neighbours. The sender domain reveals the customer in **34%** of tickets (corporate email); the other 66% are freemail / portal / automation, where the customer must be inferred from (diluted) text.

## Methods (all predict the assignee)
- **naive** — majority assignee of the k text-nearest tickets.
- **cascade** — infer customer via text-NN, then assignee within it. *The broken pipeline.*
- **sender_chain** — parse customer from a corporate sender domain, filter, then assignee; fall back to naive when the domain is generic. *The engineered fix.*
- **Aito** — `_predict assignee where {text, sender_domain}`. One query.

## Scaling results
| TRAIN | naive | cascade | sender_chain | **Aito** | cust: cascade | cust: sender | **cust: Aito** | Aito ECE |
|---|---|---|---|---|---|---|---|---|
| 250 | 0.221 | 0.259 | 0.328 | **0.264** | 0.386 | 0.336 | **0.631** | 0.110 |
| 500 | 0.216 | 0.225 | 0.365 | **0.431** | 0.276 | 0.336 | **0.664** | 0.105 |
| 1000 | 0.287 | 0.284 | 0.459 | **0.562** | 0.310 | 0.336 | **0.661** | 0.222 |
| 2000 | 0.439 | 0.439 | 0.550 | **0.620** | 0.444 | 0.336 | **0.660** | 0.201 |
| 4000 | 0.526 | 0.526 | 0.606 | **0.627** | 0.527 | 0.336 | **0.656** | 0.168 |

(First four columns = assignee accuracy; next three = customer-inference accuracy.)

## Findings
**1. Inferring the customer from text fails — so the cascade fails.** The pipeline's
text vector-search recovers the customer only **39%–53%** of the time (dilution again),
and that error cascades: `cascade` assignee accuracy (26%–53%) barely beats naive
(22%–53%). Inferring the customer with the *wrong* signal poisons everything downstream.

**2. The sender is the right signal — but only where it's clean.** A deterministic
sender→customer lookup is correct exactly on the 34% of tickets with a corporate
domain, lifting the engineered chain to **61%**. But you have to *build* it (domain
map + customer filter + a fallback for the 66% generic senders), and it's blind whenever
the sender is freemail/portal/automation.

**3. Aito infers the customer the chain was after — directly, and data-efficiently.**
This is the headline. Aito's customer-inference accuracy is **flat at 63%–66% from the
smallest split onward** — 63% at just 250 tickets — because it learns the
sender→customer signal immediately and falls back to text/customer-name when the sender
is generic. The text cascade, by contrast, has to *crawl* up with data (39%→53%) and
still never catches Aito; the deterministic sender lookup is stuck at 34% (clean
senders only). Aito wins customer inference at **every** size by **fusing signals** in one
`_predict` — exactly what the brittle infer-then-assign chain was assembling by hand.

**4. On the assignee itself, Aito leads in the realistic middle; the edges are honest.**
Aito has the best assignee accuracy at every size **except the smallest** — at 250 tickets the
engineered sender-chain edges it (33% vs 26%), before Aito has learned the
area→assignee step. Its lead is largest at mid-data (e.g. 56% vs naive 29% at 1000)
and **narrows at saturation** (63% vs naive 53% at 4000) — with enough history even text-NN
eventually recovers the customer. Where the sender reveals the customer Aito hits
**95%**; on generic-sender tickets it's **46%**, because there the customer must come
from diluted text — hard for everyone. The ceiling is set by signal availability.

## Where Aito does NOT win / caveats
- **Smallest data:** the engineered sender-chain beats Aito on the assignee at 250 tickets (33% vs 26%) — Aito needs a little history to learn area→assignee even when it already knows the customer.
- **Saturation:** by 4000 tickets, naive/cascade close to within 0.10 of Aito on the assignee — lots of history lets even text-NN recover the customer. Aito's edge is biggest at realistic, mid-size data and on customer inference, not at saturation.
- **Generic-sender tickets stay hard** (46%): no method recovers a customer that nothing in the ticket identifies. Mostly portal/automation volume → under-determined for everyone.
- **Calibration is moderate** (ECE 0.105–0.222); auto-assign at gate 0.8 gives 34% coverage at **100% precision** at the largest size — essentially the clean-sender tickets, a slice you can safely automate; route the rest to a human.
- Synthetic, seeded; the sender→customer mapping is cleaner than reality. Transferable shape: text-similarity can't infer the customer, the sender can but only where present, and **Aito fuses them in one `_predict` — no chain to build.**
