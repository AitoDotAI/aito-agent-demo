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

`scripts/seed_company.py` draws churn first, in `build_customers`, from the customer's
own attributes (plan, health, onboarding, tenure, nps_band, csm_motion by size). The child
tables come after, and none of their outcomes reads churn:

- tickets, deals, invoices and feedback pick their customer at random (`c = _pick(rng, customers)`);
  usage loops over every customer, 1 to 4 products each;
- each outcome depends on the row's own attributes (ticket category, channel and first
  response; deal source and nurture track; usage adoption and onboarding push; invoice
  term; feedback theme) plus the customer's `size`, and for feedback and invoices also its `plan`.

So a bad-CSAT ticket, an overdue invoice or inactive usage carries no information about
that customer's churn beyond what its plan and size already say, and the engine correctly finds no lift.
Regenerating the data to plant one would change every published /company number,
so it is out of scope.

## Where the graph story does live

A graph fixture with planted, measured effects (corroboration where `$distinctLength`
separates independent sources from repeats, industry-to-vendor link prediction, linked
events that change outcomes) is being prepared in aito-python-tools' graph sandbox. Put
predictive graph claims there, with their measurements, not on /company.

One of its stories, "a deal wins more often when the company's use of Initech is
corroborated", cannot be one query on v2.10.x. From `deals` it needs a nested `$refs`
filter (company, then its claims, then their evidence) and a condition on a
`$distinctLength`. Until Stage 3 of the path model ships (nested `$exists` / `$refs` as
filters, td-20260927120731197939), the sandbox carries a derived `companies.initech_use`
column computed from the claims' corroboration. Any view or doc that uses it must say
"precomputed from the claims' corroboration" and must not present it as a live
traversal. When Stage 3 ships, replace the column with the query and make that view its
showcase.

## Re-checking

Re-run the node-classification query above for each row of the table and compare with
the base churn rate. If a future data change makes any lift clearly leave 1.0, update this
page before changing any copy.
