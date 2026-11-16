"""The demographic router of the SQL guard (HLD 8.7, ADR 0005).

A query that uses age, gender, state or city is demographic. A row list of Customers gets a
refusal `pii`. An aggregate goes to the threshold view (k = 5) with `WITH AGGREGATION_THRESHOLD`,
or, when the view is not available, gets `HAVING COUNT(DISTINCT id) >= k`.

The router supports the shape that the spike proved: one aggregate level over the scoped data.
All functions work on a tree that `qualify()` made, so each column has its table alias.
"""

from dataclasses import dataclass

from sqlglot import exp

from dca.core.schema import DEMOGRAPHIC_COLUMNS, SCOPED_CUSTOMERS, SCOPED_ORDER_ITEMS

THRESHOLD_VIEW = "customer_sales_threshold"
THRESHOLD_CTE = "_dca_demographic"

# (scoped view, column) -> column of the threshold view
_THRESHOLD_COLUMNS = {
    (SCOPED_ORDER_ITEMS.name, "user_id"): "user_id",
    (SCOPED_ORDER_ITEMS.name, "order_id"): "order_id",
    (SCOPED_ORDER_ITEMS.name, "sale_price"): "sale_price",
    (SCOPED_ORDER_ITEMS.name, "status"): "status",
    (SCOPED_ORDER_ITEMS.name, "created_at"): "created_at",
    (SCOPED_ORDER_ITEMS.name, "brand"): "brand",
    (SCOPED_ORDER_ITEMS.name, "category"): "category",
    (SCOPED_CUSTOMERS.name, "id"): "user_id",
    (SCOPED_CUSTOMERS.name, "age"): "age",
    (SCOPED_CUSTOMERS.name, "gender"): "gender",
    (SCOPED_CUSTOMERS.name, "state"): "state",
    (SCOPED_CUSTOMERS.name, "city"): "city",
    (SCOPED_CUSTOMERS.name, "country"): "country",
}


def rules_text() -> str:
    """The supported shape for the LLM instruction. The columns come from the router itself."""
    columns: dict[str, list[str]] = {}
    for view, column in _THRESHOLD_COLUMNS:
        columns.setdefault(view, []).append(column)
    allowed = "\n".join(f"  {view}: {', '.join(names)}" for view, names in columns.items())
    return (
        "A query that uses age, gender, state or city must have this shape, or the system blocks it:\n"
        "- One SELECT with GROUP BY. No CTE, UNION or subquery.\n"
        "- FROM scoped_customers, optionally JOIN scoped_order_items ON scoped_customers.id = scoped_order_items.user_id.\n"
        "- Only these columns:\n" + allowed + "\n"
        "- No Customer ID in the output or in GROUP BY. Count Customers with COUNT(DISTINCT scoped_customers.id).\n"
        "- The system hides groups with fewer than 5 Customers. For a comparison, run one query for each part."
    )


@dataclass(frozen=True)
class Shape:
    sources: dict[str, str]  # table alias -> scoped view name
    customers_alias: str


def sources(select: exp.Select) -> dict[str, str]:
    """The table alias and the table name of each table in the FROM and JOIN parts."""
    tables = []
    from_ = select.args.get("from_")
    if from_ is not None:
        tables.append(from_.this)
    tables.extend(join.this for join in select.args.get("joins") or [])
    return {table.alias_or_name.lower(): table.name.lower() for table in tables if isinstance(table, exp.Table)}


def _is_customer_id(column: exp.Expression, select_sources: dict[str, str]) -> bool:
    if not isinstance(column, exp.Column):
        return False
    name = column.name.lower()
    return name == "user_id" or (name == "id" and select_sources.get(column.table.lower()) == SCOPED_CUSTOMERS.name)


def customer_outputs(tree: exp.Query) -> tuple[str, ...]:
    """The output columns that hold a Customer ID (HLD 10.5)."""
    select = tree if isinstance(tree, exp.Select) else next(tree.find_all(exp.Select), None)
    if select is None:
        return ()
    select_sources = sources(select)
    return tuple(
        projection.alias_or_name
        for projection in select.expressions
        if _is_customer_id(projection.unalias(), select_sources)
    )


def is_demographic(tree: exp.Query) -> bool:
    return any(column.name.lower() in DEMOGRAPHIC_COLUMNS for column in tree.find_all(exp.Column))


def _outer_selects(tree: exp.Expression) -> list[exp.Select]:
    if isinstance(tree, exp.SetOperation):
        return _outer_selects(tree.left) + _outer_selects(tree.right)
    if isinstance(tree, exp.Subquery):
        return _outer_selects(tree.this)
    return [tree] if isinstance(tree, exp.Select) else []


def is_row_list(tree: exp.Query) -> bool:
    """Customer grain: a Customer ID in the output or in GROUP BY, or no aggregation at all.

    Only the outer SELECT gives rows to the LLM, so only its output and its groups count.
    """
    if not any(tree.find_all(exp.AggFunc)):
        return True
    for select in _outer_selects(tree):
        select_sources = sources(select)
        group = select.args.get("group")
        grouped = list(group.expressions) if group is not None else []
        if any(_is_customer_id(p.unalias(), select_sources) for p in select.expressions):
            return True
        if any(_is_customer_id(g, select_sources) for g in grouped):
            return True
    return False


def _table_columns(select: exp.Select) -> list[exp.Column]:
    """The columns of the tables, without references to output aliases (ORDER BY spend)."""
    aliases = {projection.alias.lower() for projection in select.expressions if projection.alias}
    return [c for c in select.find_all(exp.Column) if c.table or c.name.lower() not in aliases]


def shape(tree: exp.Query) -> Shape | str:
    """The supported shape, or the reason why the shape is not supported."""
    if not isinstance(tree, exp.Select) or tree.args.get("with_") is not None:
        return "use one SELECT with no CTE, UNION or subquery"
    if any(node is not tree for node in tree.find_all(exp.Select)):
        return "use one SELECT with no CTE, UNION or subquery"
    select_sources = sources(tree)
    views = set(select_sources.values())
    if not views <= {SCOPED_ORDER_ITEMS.name, SCOPED_CUSTOMERS.name} or len(select_sources) != len(views):
        return "use only scoped_customers, joined to scoped_order_items on scoped_customers.id = user_id"
    customers = next((alias for alias, view in select_sources.items() if view == SCOPED_CUSTOMERS.name), None)
    if customers is None:
        return "a demographic query needs scoped_customers"
    joins = tree.args.get("joins") or []
    if joins:
        condition = joins[0].args.get("on")
        if not isinstance(condition, exp.EQ) or not (
            _is_customer_id(condition.left, select_sources) and _is_customer_id(condition.right, select_sources)
        ):
            return "join scoped_order_items on scoped_customers.id = scoped_order_items.user_id"
    if views == {SCOPED_CUSTOMERS.name}:
        for function in tree.find_all(exp.AggFunc):
            if not (isinstance(function, exp.Count) and isinstance(function.this, exp.Distinct)):
                return "over scoped_customers alone, count Customers with COUNT(DISTINCT id)"
    for column in _table_columns(tree):
        if (select_sources.get(column.table.lower()), column.name.lower()) not in _THRESHOLD_COLUMNS:
            return f"the column {column.name} is not available in a demographic query"
    return Shape(sources=select_sources, customers_alias=customers)


def threshold_sql(tree: exp.Select, found: Shape, view: str) -> str:
    """The query on a scoped CTE over the threshold view, with WITH AGGREGATION_THRESHOLD."""
    tree = tree.copy()
    for column in _table_columns(tree):
        target = _THRESHOLD_COLUMNS[(found.sources[column.table.lower()], column.name.lower())]
        column.set("this", exp.to_identifier(target, quoted=True))
        column.set("table", exp.to_identifier(THRESHOLD_CTE))
    tree.set("joins", None)
    tree.set("from_", exp.From(this=exp.to_table(THRESHOLD_CTE)))
    body = tree.sql(dialect="bigquery")
    assert body.startswith("SELECT ")
    return (
        f"WITH {THRESHOLD_CTE} AS (SELECT * FROM `{view}` WHERE brand IN UNNEST(@brands)) "
        f"SELECT WITH AGGREGATION_THRESHOLD {body[len('SELECT ') :]}"
    )


def add_having(tree: exp.Select, found: Shape, k: int) -> None:
    """The fallback when the threshold view is not available: hide groups with fewer than k Customers."""
    condition = exp.GTE(
        this=exp.Count(this=exp.Distinct(expressions=[exp.column("id", table=found.customers_alias)])),
        expression=exp.Literal.number(k),
    )
    having = tree.args.get("having")
    tree.set("having", exp.Having(this=exp.and_(having.this, condition) if having else condition))
