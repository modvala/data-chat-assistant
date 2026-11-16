"""The Brand scope rewrite (ADR 0001, HLD 8.5).

The semantic tests run the rewritten SQL on a small SQLite copy of the four tables.
"""

import re
import sqlite3

import pytest
import sqlglot
from sqlglot import exp

from dca.core import sql_guard
from dca.core.ports import Grant
from dca.core.schema import SCOPED_VIEWS

DATASET = "bigquery-public-data.thelook_ecommerce"
MANAGER = Grant("mgr_ana", "manager", ("Allegra K", "Calvin Klein"))
CEO = Grant("ceo", "ceo", ("Allegra K", "Calvin Klein", "Nike"))

QUERIES = [
    "SELECT brand, SUM(sale_price) AS revenue FROM scoped_order_items GROUP BY brand",
    "SELECT id, traffic_source, country FROM scoped_customers",
    "SELECT o.order_id, COUNT(*) AS n FROM scoped_orders o JOIN scoped_order_items i ON i.order_id = o.order_id GROUP BY 1",
    "WITH t AS (SELECT user_id, sale_price FROM scoped_order_items) SELECT c.traffic_source, SUM(t.sale_price) AS s "
    "FROM t JOIN scoped_customers c ON c.id = t.user_id GROUP BY 1",
    "SELECT scoped_orders.status FROM scoped_orders",
    "SELECT status FROM scoped_orders UNION ALL SELECT status FROM scoped_order_items",
    "SELECT user_id FROM scoped_order_items WHERE order_id IN (SELECT order_id FROM scoped_orders)",
]


def allowed(sql: str, grant: Grant = MANAGER) -> sql_guard.Allowed:
    verdict = sql_guard.check(sql, grant, source_dataset=DATASET, sql_limit=50)
    assert isinstance(verdict, sql_guard.Allowed), verdict
    return verdict


@pytest.mark.parametrize("sql", QUERIES)
def test_ac_r2_2_rewritten_sql_has_no_scoped_view_name_and_binds_brands(sql: str) -> None:
    verdict = allowed(sql)
    for name in SCOPED_VIEWS:
        assert not re.search(rf"(?<!_dca_){name}", verdict.sql), f"{name} is left in {verdict.sql}"
    assert "UNNEST(@brands)" in verdict.sql
    assert verdict.params == {"brands": MANAGER.brands}


def test_ac_r2_2_ceo_uses_the_same_rewrite_with_all_brands() -> None:
    manager, ceo = allowed(QUERIES[0], MANAGER), allowed(QUERIES[0], CEO)
    assert manager.sql == ceo.sql
    assert ceo.params == {"brands": CEO.brands}


# --- Semantic test on SQLite


def _sqlite_sql(sql: str, brands: tuple[str, ...]) -> str:
    tree = sqlglot.parse_one(sql, read="bigquery")
    for table in list(tree.find_all(exp.Table)):
        if table.args.get("db"):
            table.set("db", None)
            table.set("catalog", None)
    for node in list(tree.find_all(exp.In)):
        if node.args.get("unnest") is not None:
            node.set("unnest", None)
            node.set("expressions", [exp.Literal.string(brand) for brand in brands])
    return tree.sql(dialect="sqlite")


@pytest.fixture
def db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE products (id INT, name TEXT, brand TEXT, category TEXT, department TEXT, retail_price REAL, cost REAL);
        CREATE TABLE order_items (id INT, order_id INT, user_id INT, product_id INT, status TEXT, created_at TEXT,
            shipped_at TEXT, delivered_at TEXT, returned_at TEXT, sale_price REAL);
        CREATE TABLE orders (order_id INT, user_id INT, status TEXT, created_at TEXT, shipped_at TEXT,
            delivered_at TEXT, returned_at TEXT, num_of_item INT);
        CREATE TABLE users (id INT, first_name TEXT, email TEXT, age INT, gender TEXT, city TEXT, state TEXT,
            country TEXT, traffic_source TEXT, created_at TEXT);
        INSERT INTO products VALUES (1, 'Jeans', 'Calvin Klein', 'Jeans', 'Men', 100, 40),
                                    (2, 'Shoes', 'Nike', 'Shoes', 'Men', 50, 20);
        -- Order 10 has one item of each brand. Order 11 has only a Nike item.
        INSERT INTO order_items VALUES (100, 10, 7, 1, 'Complete', '2026-10-01', NULL, NULL, NULL, 100.0),
                                       (101, 10, 7, 2, 'Complete', '2026-10-01', NULL, NULL, NULL, 50.0),
                                       (102, 11, 8, 2, 'Complete', '2026-10-02', NULL, NULL, NULL, 50.0);
        INSERT INTO orders VALUES (10, 7, 'Complete', '2026-10-01', NULL, NULL, NULL, 2),
                                  (11, 8, 'Complete', '2026-10-02', NULL, NULL, NULL, 1);
        INSERT INTO users VALUES (7, 'Ann', 'ann@example.com', 30, 'F', 'Boston', 'MA', 'US', 'Search', '2025-01-01'),
                                 (8, 'Bob', 'bob@example.com', 40, 'M', 'Austin', 'TX', 'US', 'Email', '2025-01-01');
        """
    )
    return connection


def run(db: sqlite3.Connection, sql: str, grant: Grant = MANAGER) -> list[tuple]:
    verdict = allowed(sql, grant)
    return db.execute(_sqlite_sql(verdict.sql, verdict.params["brands"])).fetchall()


def test_ac_r2_2_multi_brand_order_counts_only_items_in_scope(db: sqlite3.Connection) -> None:
    rows = run(db, "SELECT order_id, SUM(sale_price) AS total FROM scoped_order_items GROUP BY order_id")
    assert rows == [(10, 100.0)]


def test_ac_r2_2_orders_and_customers_come_only_through_items_in_scope(db: sqlite3.Connection) -> None:
    assert run(db, "SELECT order_id FROM scoped_orders") == [(10,)]
    assert run(db, "SELECT id, traffic_source FROM scoped_customers") == [(7, "Search")]


def test_ac_r2_2_ceo_sees_all_items(db: sqlite3.Connection) -> None:
    rows = run(db, "SELECT order_id, SUM(sale_price) AS total FROM scoped_order_items GROUP BY order_id ORDER BY 1", CEO)
    assert rows == [(10, 150.0), (11, 50.0)]


def test_ac_r2_2_join_of_orders_and_items_keeps_the_item_filter(db: sqlite3.Connection) -> None:
    rows = run(
        db,
        "SELECT o.order_id, SUM(i.sale_price) AS total FROM scoped_orders o "
        "JOIN scoped_order_items i ON i.order_id = o.order_id GROUP BY o.order_id",
    )
    assert rows == [(10, 100.0)]
