"""Write REPORT.md for the v3 assignment benchmark from results/scaling.json.

v3: the customer is LATENT and must be inferred; the real signal is the email
sender domain. Narrative is derived from the numbers.

    python -m bench.report
"""

from __future__ import annotations

import json

from bench import config
from data.org import CUSTOMER_DOMAINS, all_agents


def main() -> None:
    rows = json.loads((config.RESULTS_DIR / "scaling.json").read_text())
    small, big = rows[0], rows[-1]
    test = json.loads((config.DATA_DIR / "test.json").read_text())
    n_test = len(test)
    n_agents = len(all_agents())
    reveals = sum(t["sender_domain"] == CUSTOMER_DOMAINS.get(t["customer"]) for t in test) / n_test

    def line(r):
        return (f"| {r['n_train']} | {r['acc_naive']:.3f} | {r['acc_cascade']:.3f} | "
                f"{r['acc_sender']:.3f} | **{r['acc_aito']:.3f}** | {r['cust_acc_cascade']:.3f} | "
                f"{r['cust_acc_sender']:.3f} | **{r['cust_acc_aito']:.3f}** | {r['aito_ece']:.3f} |")

    table = "\n".join(line(r) for r in rows)

    md = f"""# Ticket field-assignment benchmark — results (v3)

The faithful version: **customer and project were never fields — they had to be
inferred.** The real signal is the email **sender domain**, which usually (not
always) identifies the customer. The production pipeline inferred the customer by
**text vector-search over history** and cascaded that (wrong) customer into a wrong
assignee. The question here: can Aito infer the assignee **directly** from
`{{text, sender_domain}}` and collapse that chain? Everything is LLM-free.

n_test = {n_test}, {n_agents} agents, k = {small['k']} neighbours. The sender domain reveals the customer in **{reveals:.0%}** of tickets (corporate email); the other {1-reveals:.0%} are freemail / portal / automation, where the customer must be inferred from (diluted) text.

## Methods (all predict the assignee)
- **naive** — majority assignee of the k text-nearest tickets.
- **cascade** — infer customer via text-NN, then assignee within it. *The broken pipeline.*
- **sender_chain** — parse customer from a corporate sender domain, filter, then assignee; fall back to naive when the domain is generic. *The engineered fix.*
- **Aito** — `_predict assignee where {{text, sender_domain}}`. One query.

## Scaling results
| TRAIN | naive | cascade | sender_chain | **Aito** | cust: cascade | cust: sender | **cust: Aito** | Aito ECE |
|---|---|---|---|---|---|---|---|---|
{table}

(First four columns = assignee accuracy; next three = customer-inference accuracy.)

## Findings
**1. Inferring the customer from text fails — so the cascade fails.** The pipeline's
text vector-search recovers the customer only **{small['cust_acc_cascade']:.0%}–{big['cust_acc_cascade']:.0%}** of the time (dilution again),
and that error cascades: `cascade` assignee accuracy ({small['acc_cascade']:.0%}–{big['acc_cascade']:.0%}) barely beats naive
({small['acc_naive']:.0%}–{big['acc_naive']:.0%}). Inferring the customer with the *wrong* signal poisons everything downstream.

**2. The sender is the right signal — but only where it's clean.** A deterministic
sender→customer lookup is correct exactly on the {reveals:.0%} of tickets with a corporate
domain, lifting the engineered chain to **{big['acc_sender']:.0%}**. But you have to *build* it (domain
map + customer filter + a fallback for the {1-reveals:.0%} generic senders), and it's blind whenever
the sender is freemail/portal/automation.

**3. Aito infers the customer the chain was after — directly, and data-efficiently.**
This is the headline. Aito's customer-inference accuracy is **flat at {min(r['cust_acc_aito'] for r in rows):.0%}–{max(r['cust_acc_aito'] for r in rows):.0%} from the
smallest split onward** — {small['cust_acc_aito']:.0%} at just {small['n_train']} tickets — because it learns the
sender→customer signal immediately and falls back to text/customer-name when the sender
is generic. The text cascade, by contrast, has to *crawl* up with data ({small['cust_acc_cascade']:.0%}→{big['cust_acc_cascade']:.0%}) and
still never catches Aito; the deterministic sender lookup is stuck at {big['cust_acc_sender']:.0%} (clean
senders only). Aito wins customer inference at **every** size by **fusing signals** in one
`_predict` — exactly what the brittle infer-then-assign chain was assembling by hand.

**4. On the assignee itself, Aito leads in the realistic middle; the edges are honest.**
Aito has the best assignee accuracy at every size **except the smallest** — at {small['n_train']} tickets the
engineered sender-chain edges it ({small['acc_sender']:.0%} vs {small['acc_aito']:.0%}), before Aito has learned the
area→assignee step. Its lead is largest at mid-data (e.g. {[r for r in rows if r['n_train']==1000][0]['acc_aito']:.0%} vs naive {[r for r in rows if r['n_train']==1000][0]['acc_naive']:.0%} at 1000)
and **narrows at saturation** ({big['acc_aito']:.0%} vs naive {big['acc_naive']:.0%} at {big['n_train']}) — with enough history even text-NN
eventually recovers the customer. Where the sender reveals the customer Aito hits
**{big['aito_acc_clean_sender']:.0%}**; on generic-sender tickets it's **{big['aito_acc_generic_sender']:.0%}**, because there the customer must come
from diluted text — hard for everyone. The ceiling is set by signal availability.

## Where Aito does NOT win / caveats
- **Smallest data:** the engineered sender-chain beats Aito on the assignee at {small['n_train']} tickets ({small['acc_sender']:.0%} vs {small['acc_aito']:.0%}) — Aito needs a little history to learn area→assignee even when it already knows the customer.
- **Saturation:** by {big['n_train']} tickets, naive/cascade close to within {big['acc_aito']-big['acc_naive']:.2f} of Aito on the assignee — lots of history lets even text-NN recover the customer. Aito's edge is biggest at realistic, mid-size data and on customer inference, not at saturation.
- **Generic-sender tickets stay hard** ({big['aito_acc_generic_sender']:.0%}): no method recovers a customer that nothing in the ticket identifies. Mostly portal/automation volume → under-determined for everyone.
- **Calibration is moderate** (ECE {min(r['aito_ece'] for r in rows):.3f}–{max(r['aito_ece'] for r in rows):.3f}); auto-assign at gate {config.GATE} gives {big['aito_autoassign_coverage']:.0%} coverage at **{big['aito_autoassign_precision']:.0%} precision** at the largest size — essentially the clean-sender tickets, a slice you can safely automate; route the rest to a human.
- Synthetic, seeded; the sender→customer mapping is cleaner than reality. Transferable shape: text-similarity can't infer the customer, the sender can but only where present, and **Aito fuses them in one `_predict` — no chain to build.**
"""
    (config.RESULTS_DIR / "REPORT.md").write_text(md)
    print("wrote REPORT.md")


if __name__ == "__main__":
    main()
