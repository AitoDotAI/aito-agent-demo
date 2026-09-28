# /company graph: what the links show, and what they do not

**Claim this page protects:** the /company spotlight retrieves a customer's linked
neighbourhood (tickets, usage, deals, invoices, feedback) in one v2 `_query` and counts
independent sources with `$distinctLength`. That is retrieval and provenance. It is
**not** evidence that anything in the neighbourhood predicts churn, and on this dataset
nothing in it does. Do not add "the graph predicts churn" (or "bad tickets raise churn
risk", or similar) to /company copy, the Company AI agent prompt, or decks.

Measured 2026-09-27 on shared.aito.ai, engine 2.10.3 (gitRevision `88786b4dc970`),
`env.master`, the `customers` table (1,500 rows, base churn 0.226).

## The non-lifts

Lift = P(churned = yes | the customer has a linked row matching the condition) / base
rate. Evidence entered as a v2 node-classification condition, e.g.
`{"from":"customers","where":{"$refs.tickets.customer":{"$exists":{"csat_band":"bad"}}},"predict":"churned"}`,
and cross-checked by counting.

| Linked condition                  | Churn lift |
|-----------------------------------|-----------:|
| any feedback with `score_band = detractor` | 1.05 |
| any ticket with `csat_band = bad`          | 1.00 |
| any invoice with `status = overdue`        | 1.03 |
| any usage row with `active = no`           | 0.97 |
| any ticket with `resolved = no`            | 0.97 |
| no feedback at all                         | 1.01 |

All within noise of 1.0. For contrast, the customer's own attributes do move churn:
`health = Red` gives 1.93x and `nps_band = detractor` 1.60x. Within those customers the
linked conditions still lift only 0.85 to 1.08 (Red) and 0.96 to 1.05 (detractor).

Link prediction has the same result: `_relate` drivers of `deals.product` over
`customer.industry / size / plan` and `source` lift only 0.81 to 1.13, so predicting "the
next product for this customer" from the graph would be a ranked guess.

## Why: the fixture has no cross-table signal

`scripts/seed_company.py` generates every child row as `c = _pick(rng, customers)` and draws
its outcome from that customer's `size` and `plan` only (e.g. `build_feedback`,
`build_tickets`). Churn is drawn in `build_customers` from the customer's own attributes
(plan, health, onboarding, tenure, nps_band, csm_motion by size) before any child row
exists. Nothing links a ticket's CSAT, an overdue invoice or inactive usage to that
customer's churn, so the engine correctly finds no lift. Regenerating the data to plant
one would change every published /company number, so it is out of scope.

## Where the graph story does live

A graph fixture with planted, measured effects (corroboration where `$distinctLength`
separates independent sources from repeats, industry-to-vendor link prediction, linked
events that change outcomes) is being prepared in aito-python-tools' graph sandbox. Put
predictive graph claims there, with their measurements, not on /company.

## Re-checking

Re-run the node-classification query above for each row of the table and compare with
the base churn rate. If a future data change makes any lift clearly leave 1.0, update this
page before changing any copy.
