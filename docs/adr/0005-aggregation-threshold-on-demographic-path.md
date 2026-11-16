# The native aggregation threshold applies only to the demographic path

Scope: both

BigQuery's aggregation threshold hides groups with fewer than k Customers. But it also forbids the output of the privacy unit column (`user_id`). If we put it on all Customer data, "top customers by spend" stops working, and the assignment expects this question. So our code sends only demographic queries (queries that group or filter on age, gender, state or city) to a threshold view with `privacy_unit_column = user_id` and k = 5. All other queries use the normal scoped views (ADR 0001).

- **Prototype**: `uv run setup-bq` makes the threshold view in the reviewer's own project, from [`scripts/threshold-views.sql`](../../scripts/threshold-views.sql). The ADK spike (ADR 0003) showed that this works over the public dataset. If the view is not available, the code adds `HAVING COUNT(DISTINCT user_id) >= 5` to demographic aggregates.
- **Production**: the threshold views are part of the curated dataset.

## Spike result

On 2026-11-16, the spike ran these queries as the read-only service account `dca-agent`, on the views in `scripts/threshold-views.sql`:

| Query | Result |
| --- | --- |
| Customers by city with `WITH AGGREGATION_THRESHOLD` | The raw table has 4,268 of 7,898 cities with fewer than 5 Customers. The output has 3,630 cities and no group under 5. |
| An aggregate without `WITH AGGREGATION_THRESHOLD` | Error. The view forces the clause. |
| `SELECT user_id`, and `GROUP BY user_id` with or without the clause | Error |
| `WHERE brand IN UNNEST(@brands)` on the view of Customer sales | Works |
| The scoped CTE of ADR 0001 over the view, then `WITH AGGREGATION_THRESHOLD` | Works |
| A dry run of a threshold query | Works |

Consequences:

- The demographic router must add `WITH AGGREGATION_THRESHOLD` to each query that it sends to a threshold view. If it does not, BigQuery refuses the query. Thus a router bug causes an error, not a leak.
- In the BigQuery sandbox, the views expire after 60 days. `setup-bq` uses `CREATE OR REPLACE`, so the reviewer can run it again. An expired view is the case where the `HAVING` fallback applies.

## Considered options

- **Threshold on all Customer data**: breaks "top customers".
- **Plain `HAVING` only**: works everywhere, but it is our code, not a BigQuery guarantee.
