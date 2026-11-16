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
        "SELECT * FROM scoped_customers",
        "SELECT id AS customer, age FROM scoped_customers",
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
    result = verdict("SELECT * FROM scoped_customers")
    assert isinstance(result, sql_guard.Allowed)
    select_list = result.sql.split(" FROM `_dca_scoped_customers`")[0].rsplit("SELECT ", 1)[1]
    assert "email" not in select_list and "`id`" in select_list and "`age`" in select_list
