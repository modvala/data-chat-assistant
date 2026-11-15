# The native aggregation threshold applies only to the demographic path

Scope: both

BigQuery's aggregation threshold hides groups with fewer than k Customers. But it also forbids the output of the privacy unit column (`user_id`). If we put it on all Customer data, "top customers by spend" stops working, and the assignment expects this question. So our code sends only demographic queries (queries that group or filter on age, gender, state or city) to a threshold view with `privacy_unit_column = user_id` and k = 5. All other queries use the normal scoped views (ADR 0001).

- **Prototype**: `uv run setup-bq` makes the threshold view in the reviewer's own project. The ADK spike (ADR 0003) checks that this works over the public dataset. If it does not work, the code adds `HAVING COUNT(DISTINCT user_id) >= 5` to demographic aggregates.
- **Production**: the threshold views are part of the curated dataset.

## Considered options

- **Threshold on all Customer data**: breaks "top customers".
- **Plain `HAVING` only**: works everywhere, but it is our code, not a BigQuery guarantee.
