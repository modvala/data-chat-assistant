"""The three scoped views (ADR 0001, HLD 8.5).

The LLM writes SQL only against these views. The columns here are the allowlist of the
SQL guard: a PII column is not in a view, so no query can read it.
"""

from dataclasses import dataclass

PII_COLUMNS = frozenset(
    {"first_name", "last_name", "email", "street_address", "postal_code", "latitude", "longitude", "user_geom"}
)
DEMOGRAPHIC_COLUMNS = frozenset({"age", "gender", "state", "city"})


@dataclass(frozen=True)
class ViewColumn:
    name: str
    type: str
    description: str
    source: str


@dataclass(frozen=True)
class ScopedView:
    name: str
    description: str
    columns: tuple[ViewColumn, ...]
    customer_id_column: str


SCOPED_ORDER_ITEMS = ScopedView(
    name="scoped_order_items",
    description="One row for each order item of a product in the Brand scope. Revenue comes from this view only.",
    customer_id_column="user_id",
    columns=(
        ViewColumn("id", "INT64", "Order item ID", "oi.id"),
        ViewColumn("order_id", "INT64", "Order ID", "oi.order_id"),
        ViewColumn("user_id", "INT64", "Customer ID", "oi.user_id"),
        ViewColumn("product_id", "INT64", "Product ID", "oi.product_id"),
        ViewColumn("status", "STRING", "Item status: Complete, Shipped, Processing, Cancelled, Returned", "oi.status"),
        ViewColumn("created_at", "TIMESTAMP", "Time of the order", "oi.created_at"),
        ViewColumn("shipped_at", "TIMESTAMP", "Time of shipping", "oi.shipped_at"),
        ViewColumn("delivered_at", "TIMESTAMP", "Time of delivery", "oi.delivered_at"),
        ViewColumn("returned_at", "TIMESTAMP", "Time of return", "oi.returned_at"),
        ViewColumn("sale_price", "FLOAT64", "Price paid for the item, in USD", "oi.sale_price"),
        ViewColumn("product_name", "STRING", "Product name", "p.name"),
        ViewColumn("brand", "STRING", "Product brand", "p.brand"),
        ViewColumn("category", "STRING", "Product category", "p.category"),
        ViewColumn("department", "STRING", "Product department: Men or Women", "p.department"),
        ViewColumn("retail_price", "FLOAT64", "List price of the product, in USD", "p.retail_price"),
        ViewColumn("cost", "FLOAT64", "Cost of the product, in USD", "p.cost"),
    ),
)

SCOPED_ORDERS = ScopedView(
    name="scoped_orders",
    description=(
        "One row for each order with at least one item in the Brand scope. Order-level columns only. "
        "For item counts and revenue, use scoped_order_items."
    ),
    customer_id_column="user_id",
    columns=(
        ViewColumn("order_id", "INT64", "Order ID", "o.order_id"),
        ViewColumn("user_id", "INT64", "Customer ID", "o.user_id"),
        ViewColumn("status", "STRING", "Order status", "o.status"),
        ViewColumn("created_at", "TIMESTAMP", "Time of the order", "o.created_at"),
        ViewColumn("shipped_at", "TIMESTAMP", "Time of shipping", "o.shipped_at"),
        ViewColumn("delivered_at", "TIMESTAMP", "Time of delivery", "o.delivered_at"),
        ViewColumn("returned_at", "TIMESTAMP", "Time of return", "o.returned_at"),
    ),
)

SCOPED_CUSTOMERS = ScopedView(
    name="scoped_customers",
    description="One row for each Customer with at least one purchase in the Brand scope. No personal data.",
    customer_id_column="id",
    columns=(
        ViewColumn("id", "INT64", "Customer ID", "u.id"),
        ViewColumn("age", "INT64", "Age in years", "u.age"),
        ViewColumn("gender", "STRING", "M or F", "u.gender"),
        ViewColumn("city", "STRING", "City", "u.city"),
        ViewColumn("state", "STRING", "State or region", "u.state"),
        ViewColumn("country", "STRING", "Country", "u.country"),
        ViewColumn("traffic_source", "STRING", "How the Customer found the shop", "u.traffic_source"),
        ViewColumn("created_at", "TIMESTAMP", "Time of sign-up", "u.created_at"),
    ),
)

SCOPED_VIEWS = {view.name: view for view in (SCOPED_ORDER_ITEMS, SCOPED_ORDERS, SCOPED_CUSTOMERS)}

# The rewrite renames each scoped view to an internal CTE name, so no scoped view name is left.
CTE_PREFIX = "_dca_"


def cte_name(view_name: str) -> str:
    return f"{CTE_PREFIX}{view_name}"


def sqlglot_schema() -> dict[str, dict[str, str]]:
    """The allowlist as a sqlglot schema: view name -> column name -> type."""
    return {view.name: {column.name: column.type for column in view.columns} for view in SCOPED_VIEWS.values()}


def scoped_ctes(source_dataset: str) -> dict[str, str]:
    """The CTE body of each scoped view, in dependency order. `@brands` comes from the grant."""

    def select_list(view: ScopedView) -> str:
        return ", ".join(
            column.source if column.source.endswith(f".{column.name}") else f"{column.source} AS {column.name}"
            for column in view.columns
        )

    items = cte_name(SCOPED_ORDER_ITEMS.name)
    return {
        items: (
            f"SELECT {select_list(SCOPED_ORDER_ITEMS)} "
            f"FROM `{source_dataset}.order_items` AS oi "
            f"JOIN `{source_dataset}.products` AS p ON p.id = oi.product_id "
            "WHERE p.brand IN UNNEST(@brands)"
        ),
        cte_name(SCOPED_ORDERS.name): (
            f"SELECT {select_list(SCOPED_ORDERS)} FROM `{source_dataset}.orders` AS o "
            f"WHERE o.order_id IN (SELECT order_id FROM {items})"
        ),
        cte_name(SCOPED_CUSTOMERS.name): (
            f"SELECT {select_list(SCOPED_CUSTOMERS)} FROM `{source_dataset}.users` AS u "
            f"WHERE u.id IN (SELECT user_id FROM {items})"
        ),
    }


def describe() -> str:
    """The schema description of the scoped views, for the context and for schema questions."""
    lines = []
    for view in SCOPED_VIEWS.values():
        lines.append(f"{view.name}: {view.description}")
        lines.extend(f"  - {column.name} ({column.type}): {column.description}" for column in view.columns)
    return "\n".join(lines)
