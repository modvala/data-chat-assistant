"""The SQL guard (HLD 8.4) and the Brand scope rewrite (HLD 8.5, ADR 0001).

`check` is a pure function: it does no I/O. The dry run is a separate step of the
`run_query` tool, through the `Warehouse` port.
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify

from dca.core.ports import Grant
from dca.core.schema import CTE_PREFIX, PII_COLUMNS, SCOPED_VIEWS, cte_name, scoped_ctes, sqlglot_schema

DIALECT = "bigquery"

# Typed reasons go to the LLM only. The Executive does not see them (HLD 8.4).
SYNTAX_ERROR = "syntax_error"
NOT_READ_ONLY = "not_read_only"
RAW_TABLE = "raw_table"
UNKNOWN_COLUMN = "unknown_column"

# Refusal reasons: the Executive gets a refusal, and the LLM gets only "not permitted".
PII = "pii"
SCOPE = "scope"

_LLM_TEXT = {
    SYNTAX_ERROR: "The SQL does not parse. Fix the syntax. Detail: {detail}",
    NOT_READ_ONLY: "Only one SELECT statement is permitted. No DML, DDL or scripts.",
    RAW_TABLE: "Use only the views scoped_order_items, scoped_orders and scoped_customers, with no dataset name.",
    UNKNOWN_COLUMN: "A column is not in the schema. Use only the columns of the scoped views. Detail: {detail}",
}

_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Into,
)


@dataclass(frozen=True)
class Allowed:
    sql: str
    params: dict[str, tuple[str, ...]]
    route: str = "scoped"


@dataclass(frozen=True)
class Blocked:
    """`refusal` True: the Executive gets a refusal, and the LLM gets no retry."""

    reason: str
    refusal: bool = False
    detail: str = ""
    llm_text: str = field(default="", compare=False)


Verdict = Allowed | Blocked


def _technical(reason: str, detail: str = "") -> Blocked:
    return Blocked(reason=reason, detail=detail, llm_text=_LLM_TEXT[reason].format(detail=detail))


def check(sql: str, grant: Grant, *, source_dataset: str, sql_limit: int) -> Verdict:
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except SqlglotError as error:
        return _technical(SYNTAX_ERROR, str(error).splitlines()[0])
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        return _technical(NOT_READ_ONLY)
    tree = statements[0]
    if any(tree.find_all(*_WRITE_NODES)):
        return _technical(NOT_READ_ONLY)

    if (blocked := _check_tables(tree)) is not None:
        return blocked
    if _uses_pii(tree):
        return Blocked(reason=PII, refusal=True, detail="pii column")

    try:
        tree = qualify(tree, schema=sqlglot_schema(), dialect=DIALECT, validate_qualify_columns=True)
    except OptimizeError as error:
        return _technical(UNKNOWN_COLUMN, str(error).splitlines()[0])

    if not grant.all_brands and _brand_literals(tree) - {brand.lower() for brand in grant.brands}:
        return Blocked(reason=SCOPE, refusal=True, detail="brand literal outside the Brand scope")

    _cap_limit(tree, sql_limit)
    return Allowed(sql=_rewrite(tree, source_dataset), params={"brands": grant.brands})


def _uses_pii(tree: exp.Query) -> bool:
    """Any identifier with a PII name: a column, an alias, a struct field (allowlist, HLD 8.4)."""
    return any(identifier.name.lower() in PII_COLUMNS for identifier in tree.find_all(exp.Identifier))


def _brand_literals(tree: exp.Query) -> set[str]:
    """The string literals that a filter compares with the `brand` column, in lower case."""

    def is_brand(node: exp.Expression | None) -> bool:
        return isinstance(node, exp.Column) and node.name.lower() == "brand"

    found: set[str] = set()
    for node in tree.find_all(exp.EQ, exp.In):
        if isinstance(node, exp.EQ):
            for side, other in ((node.left, node.right), (node.right, node.left)):
                if is_brand(side) and isinstance(other, exp.Literal) and other.is_string:
                    found.add(other.this.lower())
        elif is_brand(node.this):
            values = list(node.expressions)
            unnest = node.args.get("unnest")
            if unnest is not None:
                values += [value for array in unnest.find_all(exp.Array) for value in array.expressions]
            found.update(value.this.lower() for value in values if isinstance(value, exp.Literal) and value.is_string)
    return found


def _cap_limit(tree: exp.Query, sql_limit: int) -> None:
    """Adds `LIMIT n`, or lowers a larger `LIMIT` to n (V19)."""
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(value, exp.Literal) and not value.is_string and int(value.this) <= sql_limit:
        return
    if isinstance(limit, exp.Limit):
        limit.set("expression", exp.Literal.number(sql_limit))
    else:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(sql_limit)))


def _check_tables(tree: exp.Query) -> Blocked | None:
    llm_ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    if llm_ctes & set(SCOPED_VIEWS) or any(name.startswith(CTE_PREFIX) for name in llm_ctes):
        return _technical(RAW_TABLE)
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        qualified = bool(table.args.get("db") or table.args.get("catalog"))
        if qualified or name.startswith(CTE_PREFIX) or (name not in SCOPED_VIEWS and name not in llm_ctes):
            return _technical(RAW_TABLE)
        if name in SCOPED_VIEWS:
            table.set("this", exp.to_identifier(name))  # Scoped_Orders and scoped_orders are the same view.
    return None


def _rewrite(tree: exp.Query, source_dataset: str) -> str:
    """Replace each scoped view with an internal CTE over the raw tables, filtered by `@brands`."""
    used: set[str] = set()
    for table in list(tree.find_all(exp.Table)):
        name = table.name.lower()
        if name in SCOPED_VIEWS:
            used.add(name)
            table.set("this", exp.to_identifier(cte_name(name), quoted=True))
    # qualify() gave each table an alias. An alias equal to a view name is renamed too.
    for node in tree.find_all(exp.TableAlias, exp.Column):
        identifier = node.args.get("this") if isinstance(node, exp.TableAlias) else node.args.get("table")
        if isinstance(identifier, exp.Identifier) and identifier.name.lower() in SCOPED_VIEWS:
            identifier.set("this", cte_name(identifier.name.lower()))

    bodies = scoped_ctes(source_dataset)
    needed = [name for name in bodies if name == cte_name("scoped_order_items") or name[len(CTE_PREFIX) :] in used]
    ours = [
        exp.CTE(this=sqlglot.parse_one(bodies[name], read=DIALECT), alias=exp.TableAlias(this=exp.to_identifier(name)))
        for name in needed
    ]
    existing = tree.args.get("with_")
    tree.set("with_", exp.With(expressions=ours + (list(existing.expressions) if existing else [])))
    return tree.sql(dialect=DIALECT)
