"""PROTOTYPE, throwaway. ADR 0003 check 4 (ADR 0005, HLD open question 3).

    uv run python prototypes/adk_spike/spike_bq_threshold.py

Runs as the identity of the application default credentials. With
impersonation, this is the dca-agent service account (read-only).
"""

import json
import os

import google.auth
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
V_CUSTOMERS = f"`{PROJECT}.dca_views.customers_threshold`"
V_SALES = f"`{PROJECT}.dca_views.customer_sales_threshold`"
RAW_USERS = "`bigquery-public-data.thelook_ecommerce.users`"

credentials, _ = google.auth.default()
client = bigquery.Client(project=PROJECT, credentials=credentials)
identity = getattr(credentials, "service_account_email", None) or getattr(credentials, "signer_email", None)
print(f"Project: {PROJECT}, identity: {identity or type(credentials).__name__}")

results: dict[str, str] = {}


def run(name: str, sql: str, params: list | None = None, dry_run: bool = False):
    config = bigquery.QueryJobConfig(query_parameters=params or [], dry_run=dry_run, use_query_cache=False)
    print(f"\n--- {name}\n{sql.strip()}")
    try:
        job = client.query(sql, job_config=config)
        if dry_run:
            print(f"dry run OK, bytes: {job.total_bytes_processed}")
            return job
        rows = [dict(r) for r in job.result()]
        print(f"rows: {len(rows)}, first: {json.dumps(rows[:3], default=str)}")
        return rows
    except Exception as error:  # noqa: BLE001 - the error is the result here
        print(f"ERROR: {type(error).__name__}: {str(error)[:400]}")
        return error


brands = [bigquery.ArrayQueryParameter("brands", "STRING", ["Calvin Klein", "Levi's"])]

# 4a. Small groups are hidden.
raw = run(
    "4a raw: cities with fewer than 5 customers (no threshold)",
    f"SELECT COUNTIF(n < 5) AS small_cities, COUNT(*) AS cities FROM "
    f"(SELECT city, COUNT(DISTINCT id) AS n FROM {RAW_USERS} GROUP BY city)",
)
thr = run(
    "4a threshold: customers by city",
    f"SELECT WITH AGGREGATION_THRESHOLD city, COUNT(DISTINCT user_id) AS customers FROM {V_CUSTOMERS} GROUP BY city",
)
if isinstance(raw, list) and isinstance(thr, list):
    small_in_output = sum(1 for r in thr if r["customers"] < 5)
    print(f"raw small cities: {raw[0]['small_cities']} of {raw[0]['cities']}; "
          f"output cities: {len(thr)}; output groups under 5: {small_in_output}")
    results["4a small groups hidden"] = "PASS" if raw[0]["small_cities"] > 0 and small_in_output == 0 and len(thr) < raw[0]["cities"] else "FAIL"
else:
    results["4a small groups hidden"] = "FAIL"

# 4b. The privacy unit column cannot be selected.
leak = run("4b select user_id from the view", f"SELECT user_id, age, city FROM {V_CUSTOMERS} LIMIT 5")
results["4b user_id not selectable"] = "PASS" if isinstance(leak, Exception) else "FAIL"

# 4c. Brand scope as a query parameter on the joined view.
scoped = run(
    "4c threshold with WHERE brand IN UNNEST(@brands)",
    f"SELECT WITH AGGREGATION_THRESHOLD state, COUNT(DISTINCT user_id) AS customers, ROUND(SUM(sale_price), 2) AS revenue "
    f"FROM {V_SALES} WHERE brand IN UNNEST(@brands) GROUP BY state ORDER BY revenue DESC LIMIT 10",
    brands,
)
results["4c Brand scope parameter"] = "PASS" if isinstance(scoped, list) and scoped else "FAIL"

# 4d. The ADR 0001 rewrite shape: the scope is a CTE over the view.
cte = run(
    "4d threshold through a scoped CTE (rewrite shape of ADR 0001)",
    f"WITH scoped AS (SELECT * FROM {V_SALES} WHERE brand IN UNNEST(@brands)) "
    f"SELECT WITH AGGREGATION_THRESHOLD gender, COUNT(DISTINCT user_id) AS customers FROM scoped GROUP BY gender",
    brands,
)
results["4d scoped CTE over the view"] = "PASS" if isinstance(cte, list) and cte else "FAIL"

# 4e. Dry run works on a threshold query (P14: dry run first).
dry = run(
    "4e dry run of a threshold query",
    f"SELECT WITH AGGREGATION_THRESHOLD age, COUNT(DISTINCT user_id) AS customers FROM {V_SALES} "
    f"WHERE brand IN UNNEST(@brands) GROUP BY age",
    brands,
    dry_run=True,
)
results["4e dry run"] = "PASS" if not isinstance(dry, Exception) else "FAIL"

# 4f. Without the WITH AGGREGATION_THRESHOLD clause.
plain = run("4f aggregate without the clause", f"SELECT city, COUNT(DISTINCT user_id) AS n FROM {V_CUSTOMERS} GROUP BY city")
print("(information only: does the view force the threshold?)")

# 4g. Sandbox expiration of the views.
for view in ("customers_threshold", "customer_sales_threshold"):
    table = client.get_table(f"{PROJECT}.dca_views.{view}")
    print(f"\n{view}: expires {table.expires}")

print("\n=== ADR 0003 check 4")
for name, verdict in results.items():
    print(f"{name}: {verdict}")
print(f"4f plain aggregate on the view: {'error' if isinstance(plain, Exception) else 'runs'}")
overall = all(v == "PASS" for v in results.values())
print(f"Check 4, AGGREGATION_THRESHOLD on a view over the public dataset: {'PASS' if overall else 'FAIL'}")
