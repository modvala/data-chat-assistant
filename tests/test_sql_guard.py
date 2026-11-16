"""The SQL guard function (spec #10, seam 2). No I/O."""

import pytest

from dca.core import sql_guard
from dca.core.ports import Grant

DATASET = "bigquery-public-data.thelook_ecommerce"
MANAGER = Grant("mgr_ana", "manager", ("Allegra K", "Calvin Klein"))


def verdict(sql: str, grant: Grant = MANAGER) -> sql_guard.Verdict:
    return sql_guard.check(sql, grant, source_dataset=DATASET, sql_limit=50)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM scoped_orders WHERE TRUE", sql_guard.NOT_READ_ONLY),
        ("DROP TABLE scoped_orders", sql_guard.NOT_READ_ONLY),
        ("CREATE TABLE x AS SELECT 1 AS a", sql_guard.NOT_READ_ONLY),
        ("INSERT INTO scoped_orders (order_id) VALUES (1)", sql_guard.NOT_READ_ONLY),
        ("SELECT 1 AS a FROM scoped_orders; SELECT 2 AS b FROM scoped_orders", sql_guard.NOT_READ_ONLY),
        ("DECLARE x INT64", sql_guard.NOT_READ_ONLY),
        ("SELECT * FROM orders", sql_guard.RAW_TABLE),
        ("SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`", sql_guard.RAW_TABLE),
        ("SELECT * FROM thelook_ecommerce.scoped_orders", sql_guard.RAW_TABLE),
        ("SELECT * FROM _dca_scoped_orders", sql_guard.RAW_TABLE),
        ("WITH scoped_orders AS (SELECT 1 AS order_id) SELECT * FROM scoped_orders", sql_guard.RAW_TABLE),
        ("SELEC brand FROM scoped_order_items", sql_guard.SYNTAX_ERROR),
        ("SELECT revenu FROM scoped_order_items", sql_guard.UNKNOWN_COLUMN),
    ],
)
def test_ac_r2_1_minimal_guard_blocks_what_is_not_one_select_on_scoped_views(sql: str, reason: str) -> None:
    result = verdict(sql)
    assert isinstance(result, sql_guard.Blocked)
    assert result.reason == reason
    assert not result.refusal
    assert result.llm_text


def test_ac_r2_2_brands_come_from_the_grant_not_from_the_sql() -> None:
    result = verdict("SELECT SUM(sale_price) AS revenue FROM scoped_order_items WHERE brand IN ('Calvin Klein')")
    assert isinstance(result, sql_guard.Allowed)
    assert result.params == {"brands": ("Allegra K", "Calvin Klein")}


CEO = Grant("ceo", "ceo", ("Allegra K", "Calvin Klein", "Nike"))
PII, SCOPE = sql_guard.PII, sql_guard.SCOPE
RAW, WRITE, SYNTAX = sql_guard.RAW_TABLE, sql_guard.NOT_READ_ONLY, sql_guard.SYNTAX_ERROR

# The red-team table (P23, AC-R2.1): SQL, grant, expected reason. Each case must be blocked.
RED_TEAM = [
    # PII columns, also through aliases, expressions, subqueries, CTEs and UNION
    ("pii column", "SELECT email FROM scoped_customers", MANAGER, PII),
    ("pii alias", "SELECT c.first_name AS n FROM scoped_customers AS c", MANAGER, PII),
    ("pii concat", "SELECT CONCAT(first_name, ' ', last_name) AS who FROM scoped_customers", MANAGER, PII),
    ("pii subquery", "SELECT x FROM (SELECT street_address AS x FROM scoped_customers)", MANAGER, PII),
    ("pii cte", "WITH t AS (SELECT postal_code FROM scoped_customers) SELECT * FROM t", MANAGER, PII),
    ("pii union", "SELECT city FROM scoped_customers UNION ALL SELECT email FROM scoped_customers", MANAGER, PII),
    ("pii in filter", "SELECT id FROM scoped_customers WHERE email LIKE '%@gmail.com'", MANAGER, PII),
    ("pii geo", "SELECT ST_GEOGPOINT(longitude, latitude) AS p FROM scoped_customers", MANAGER, PII),
    ("pii geom", "SELECT user_geom FROM scoped_customers", MANAGER, PII),
    ("pii comment", "SELECT /* only an id */ email FROM scoped_customers", MANAGER, PII),
    ("pii case", "SeLeCt  EMAIL\n\tFROM   Scoped_Customers", MANAGER, PII),
    ("pii quoted", "SELECT `email` FROM scoped_customers", MANAGER, PII),
    ("pii for the ceo", "SELECT last_name FROM scoped_customers", CEO, PII),
    ("select star raw users", "SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`", CEO, RAW),
    # Statements
    ("dml", "UPDATE scoped_orders SET status = 'x' WHERE TRUE", MANAGER, WRITE),
    ("ddl", "CREATE OR REPLACE VIEW v AS SELECT 1 AS a", MANAGER, WRITE),
    ("two statements", "SELECT id FROM scoped_customers; DROP TABLE scoped_customers", MANAGER, WRITE),
    ("comment hides statement", "SELECT 1 AS a FROM scoped_orders; -- x\nDELETE FROM scoped_orders WHERE TRUE", MANAGER, WRITE),
    ("script", "BEGIN SELECT 1; END", MANAGER, WRITE),
    ("export", "EXPORT DATA OPTIONS(uri='gs://x/*') AS SELECT id FROM scoped_customers", MANAGER, WRITE),
    # Tables
    ("raw table", "SELECT * FROM users", MANAGER, RAW),
    ("raw table join", "SELECT o.order_id FROM scoped_orders AS o JOIN orders AS r ON r.order_id = o.order_id", MANAGER, RAW),
    ("public table", "SELECT SUM(sale_price) AS s FROM `bigquery-public-data.thelook_ecommerce.order_items`", CEO, RAW),
    ("information schema", "SELECT * FROM `region-us`.INFORMATION_SCHEMA.JOBS", MANAGER, RAW),
    ("internal name", "SELECT * FROM _dca_scoped_orders", MANAGER, RAW),
    ("cte shadows a view", "WITH scoped_orders AS (SELECT 1 AS order_id) SELECT * FROM scoped_orders", MANAGER, RAW),
    # Brand scope
    ("brand eq", "SELECT SUM(sale_price) AS s FROM scoped_order_items WHERE brand = 'Nike'", MANAGER, SCOPE),
    ("brand in", "SELECT SUM(sale_price) AS s FROM scoped_order_items WHERE brand IN ('Calvin Klein', 'Nike')", MANAGER, SCOPE),
    ("brand unnest", "SELECT SUM(sale_price) AS s FROM scoped_order_items WHERE brand IN UNNEST(['Nike'])", MANAGER, SCOPE),
    ("brand reversed", "SELECT SUM(sale_price) AS s FROM scoped_order_items WHERE 'Nike' = brand", MANAGER, SCOPE),
    ("brand alias", "SELECT SUM(i.sale_price) AS s FROM scoped_order_items AS i WHERE i.brand = \"Levi's\"", MANAGER, SCOPE),
    # Demographic row lists (quasi-identifiers, P9)
    ("demographic select star", "SELECT * FROM scoped_customers", MANAGER, PII),
    ("demographic filter", "SELECT id FROM scoped_customers WHERE age = 25 AND city = 'Boston'", MANAGER, PII),
    ("demographic distinct", "SELECT DISTINCT id, gender FROM scoped_customers", MANAGER, PII),
    (
        "demographic group by customer",
        "SELECT c.id, COUNT(*) AS n FROM scoped_customers AS c WHERE c.state = 'Texas' GROUP BY c.id",
        MANAGER,
        PII,
    ),
    (
        "demographic customer in output",
        "SELECT i.user_id, c.age, SUM(i.sale_price) AS s FROM scoped_order_items AS i "
        "JOIN scoped_customers AS c ON c.id = i.user_id GROUP BY 1, 2",
        CEO,
        PII,
    ),
    # Syntax
    ("syntax", "SELECT FROM WHERE", MANAGER, SYNTAX),
]


@pytest.mark.parametrize(("sql", "grant", "reason"), [row[1:] for row in RED_TEAM], ids=[row[0] for row in RED_TEAM])
def test_ac_r2_1_red_team_cases_are_all_blocked(sql: str, grant: Grant, reason: str) -> None:
    result = verdict(sql, grant)
    assert isinstance(result, sql_guard.Blocked), result
    assert result.reason == reason
    assert result.refusal == (reason in (PII, SCOPE))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM scoped_orders",
        "SELECT id AS customer, traffic_source FROM scoped_customers",
        "SELECT user_id, SUM(sale_price) AS spend FROM scoped_order_items GROUP BY user_id ORDER BY spend DESC",
        "SELECT SUM(sale_price) AS s FROM scoped_order_items WHERE brand = 'calvin klein'",
        "SELECT order_id FROM Scoped_Orders",
    ],
)
def test_ac_r2_1_allowed_queries_pass(sql: str) -> None:
    assert isinstance(verdict(sql), sql_guard.Allowed)


def test_ac_r2_2_the_ceo_can_filter_on_any_brand() -> None:
    assert isinstance(verdict("SELECT SUM(sale_price) AS s FROM scoped_order_items WHERE brand = 'Nike'", CEO), sql_guard.Allowed)


@pytest.mark.parametrize(
    ("sql", "limit"),
    [
        ("SELECT id FROM scoped_customers", "LIMIT 50"),
        ("SELECT id FROM scoped_customers LIMIT 500", "LIMIT 50"),
        ("SELECT id FROM scoped_customers LIMIT 10", "LIMIT 10"),
        ("SELECT id FROM scoped_customers LIMIT 100 OFFSET 5", "LIMIT 50 OFFSET 5"),
        ("SELECT id FROM scoped_customers UNION ALL SELECT user_id FROM scoped_orders", "LIMIT 50"),
    ],
)
def test_ac_r2_1_guard_adds_or_lowers_the_limit(sql: str, limit: str) -> None:
    result = verdict(sql)
    assert isinstance(result, sql_guard.Allowed)
    assert result.sql.endswith(limit)
    assert result.sql.count("LIMIT") == 1


def test_ac_r2_1_select_star_expands_to_the_allowlist() -> None:
    result = verdict("SELECT * FROM scoped_orders")
    assert isinstance(result, sql_guard.Allowed)
    select_list = result.sql.split(" FROM `_dca_scoped_orders`")[0].rsplit("SELECT ", 1)[1]
    assert "`order_id`" in select_list and "`status`" in select_list
    assert "num_of_item" not in select_list and "gender" not in select_list


THRESHOLD_VIEW = "proj.dca_views.customer_sales_threshold"
SPEND_BY_AGE = (
    "SELECT c.age, AVG(i.sale_price) AS avg_spend FROM scoped_customers AS c "
    "JOIN scoped_order_items AS i ON c.id = i.user_id WHERE c.city = 'Boston' GROUP BY c.age"
)
CUSTOMERS_BY_CITY = "SELECT city, COUNT(DISTINCT id) AS customers FROM scoped_customers GROUP BY city"


CUSTOMERS_BY_CITY_ORDERED = CUSTOMERS_BY_CITY + " ORDER BY customers ASC"


@pytest.mark.parametrize("sql", [SPEND_BY_AGE, CUSTOMERS_BY_CITY, CUSTOMERS_BY_CITY_ORDERED])
def test_ac_r2_3_demographic_aggregate_goes_to_the_threshold_view(sql: str) -> None:
    result = sql_guard.check(sql, MANAGER, source_dataset=DATASET, sql_limit=50, threshold_view=THRESHOLD_VIEW)
    assert isinstance(result, sql_guard.Allowed), result
    assert result.route == "threshold_view"
    assert f"FROM `{THRESHOLD_VIEW}` WHERE brand IN UNNEST(@brands)" in result.sql
    assert " SELECT WITH AGGREGATION_THRESHOLD " in result.sql
    assert "_dca_scoped" not in result.sql and "thelook_ecommerce" not in result.sql
    assert result.params == {"brands": MANAGER.brands}


@pytest.mark.parametrize("sql", [SPEND_BY_AGE, CUSTOMERS_BY_CITY])
def test_ac_r2_3_having_fallback_when_the_threshold_view_is_not_available(sql: str) -> None:
    result = sql_guard.check(sql, MANAGER, source_dataset=DATASET, sql_limit=50, threshold_view=None, threshold_k=5)
    assert isinstance(result, sql_guard.Allowed), result
    assert result.route == "having_fallback"
    assert "HAVING COUNT(DISTINCT" in result.sql and ".id) >= 5" in result.sql
    assert "AGGREGATION_THRESHOLD" not in result.sql
    assert "UNNEST(@brands)" in result.sql


@pytest.mark.parametrize(
    "sql",
    [
        "WITH t AS (SELECT city, id FROM scoped_customers) SELECT city, COUNT(DISTINCT id) AS n FROM t GROUP BY city",
        "SELECT city, n FROM (SELECT city, COUNT(DISTINCT id) AS n FROM scoped_customers GROUP BY city)",
        "SELECT city, COUNT(*) AS n FROM scoped_customers GROUP BY city",
        "SELECT c.gender, COUNT(DISTINCT o.order_id) AS n FROM scoped_customers AS c "
        "JOIN scoped_orders AS o ON o.user_id = c.id GROUP BY 1",
        "SELECT c.age, AVG(i.retail_price) AS p FROM scoped_customers AS c "
        "JOIN scoped_order_items AS i ON c.id = i.user_id GROUP BY 1",
    ],
)
def test_ac_r2_3_unsupported_demographic_shape_gives_a_typed_reason(sql: str) -> None:
    result = sql_guard.check(sql, MANAGER, source_dataset=DATASET, sql_limit=50, threshold_view=THRESHOLD_VIEW)
    assert isinstance(result, sql_guard.Blocked), result
    assert result.reason == sql_guard.UNSUPPORTED_DEMOGRAPHIC and not result.refusal
    assert "GROUP BY" in result.llm_text


def test_ac_r2_3_top_customers_by_spend_is_not_demographic() -> None:
    sql = "SELECT user_id, SUM(sale_price) AS spend FROM scoped_order_items GROUP BY user_id ORDER BY spend DESC"
    result = sql_guard.check(sql, MANAGER, source_dataset=DATASET, sql_limit=50, threshold_view=THRESHOLD_VIEW)
    assert isinstance(result, sql_guard.Allowed)
    assert result.route == "scoped" and result.customer_columns == ("user_id",)
