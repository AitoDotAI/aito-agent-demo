# /company 360: the segment as the population

**Claim this page protects:** a KPI the 360 Dashboard (and the Company AI agent's
`optimize_kpi`) shows for a segment is measured on that segment's own rows.

On shared 2.11.x a segment in `where` is evidence, not a boundary: the prior, the
`_recommend` lever ranking and the projection still came from every customer (the
2026-09-30 sanity check). Since this change (`_tool_optimize_kpi` in src/app.py):

- **current rate:** counted within the segment (`_query` totals), reported with its
  basis ("counted: 150 of 200 …");
- **lever ranking and projection:** `_recommend` and `_predict` on a nested `from`
  scoped to the segment;
- **root causes:** unchanged, already `_relate` `$on`-scoped to the segment;
- **"why" next to the headline:** still the pooled `$why`, which explains how the
  segment's attributes move the rate relative to every customer;
- **no segment:** the population is the whole table, so nothing changes (checked).

## Before and after (live, shared, 2026-10-01; now → projected (top lever))

| segment | KPI | before (segment as evidence) | after (segment as population) |
|---|---|---|---|
| size=SMB, plan=Free | conversion | 0.4 → 0.43 (Guided trial) | 0.39 → 0.53 (Self-serve) |
| size=SMB, plan=Free | churn | 0.34 → 0.23 (Exec-sponsor) | 0.32 → 0.27 (Exec-sponsor) |
| size=SMB, plan=Free | nps | 0.45 → 0.3 (Onboarding) | 0.44 → 0.17 (Onboarding) |
| size=SMB, plan=Free | csat | 0.56 → 0.62 (chat) | 0.56 → 0.67 (chat) |
| size=SMB, plan=Free | adoption | 0.49 → 0.58 (Guided) | 0.52 → 0.58 (Guided) |
| size=SMB, plan=Free | ontime | 0.45 → 0.36 (Annual) | 0.47 → 0.42 (Annual) |
| size=Enterprise | conversion | 0.33 → 0.37 (CSM-led) | 0.33 → 0.51 (CSM-led) |
| size=Enterprise | churn | 0.26 → 0.17 (Exec-sponsor) | 0.26 → 0.14 (Exec-sponsor) |
| size=Enterprise | nps | 0.39 → 0.22 (Product) | 0.39 → 0.2 (Product) |
| size=Enterprise | csat | 0.52 → 0.54 (phone) | 0.52 → 0.72 (phone) |
| size=Enterprise | adoption | 0.53 → 0.6 (Workshop) | 0.53 → 0.75 (Workshop) |
| size=Enterprise | ontime | 0.37 → 0.29 (Annual) | 0.37 → 0.22 (Annual) |
| industry=Retail | conversion | 0.36 → 0.41 (CSM-led) | 0.36 → 0.43 (Partner) |
| industry=Retail | churn | 0.26 → 0.17 (Exec-sponsor) | 0.26 → 0.16 (Exec-sponsor) |
| industry=Retail | nps | 0.33 → 0.18 (Product) | 0.33 → 0.16 (Product) |
| industry=Retail | csat | 0.57 → 0.62 (chat) | 0.57 → 0.61 (chat) |
| industry=Retail | adoption | 0.48 → 0.56 (Workshop) | 0.48 → 0.6 (Workshop) |
| industry=Retail | ontime | 0.33 → 0.26 (Annual) | 0.33 → 0.27 (Annual) |

## Checked against counts

A scoped projection should match the share already seen among the segment's rows that
have that lever (observational, not an experiment):

| segment | KPI | projected (after) | counted among rows with the lever | before |
|---|---|---|---|---|
| size=Enterprise | CSAT | 0.72 (phone) | 121/165 = 0.73 | 0.54 |
| size=Enterprise | adoption | 0.75 (Workshop) | 152/199 = 0.76 | 0.60 |
| size=SMB, plan=Free | churn | 0.27 (Exec-sponsor) | 8/31 = 0.26 | 0.23 |
| size=SMB, plan=Free | conversion | 0.53 (Self-serve) | 20/36 = 0.56 | 0.43 (Guided trial) |

The pooled version was wrong in both directions: it understated Enterprise's best
levers by about 20 points and overstated SMB/Free's churn gain more than twofold. A
projection is what the segment's own rows with that lever show; whether pulling the
lever causes it is a separate question this page does not answer.
