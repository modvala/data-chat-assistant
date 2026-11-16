"""The SQL guard function (spec #10, seam 2). No I/O."""

import pytest

from dca.core import sql_guard
from dca.core.ports import Grant

DATASET = "bigquery-public-data.thelook_ecommerce"
MANAGER = Grant("mgr_ana", "manager", ("Allegra K", "Calvin Klein"))


def verdict(sql: str, grant: Grant = MANAGER) -> sql_guard.Verdict:
    return sql_guard.check(sql, grant, source_dataset=DATASET)


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
