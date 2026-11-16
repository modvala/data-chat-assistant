"""The empty-result diagnostic (HLD 15.1, cli.md P-CORRECT).

For a query with 0 rows, our code finds the cause: it reads the real values of the filter
column and gives an info notice with the cause and a next step. The LLM does not take part.
"""

import difflib
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify

from dca.core import demographic
from dca.core.answer import Answer, Notice
from dca.core.schema import SCOPED_CUSTOMERS, SCOPED_VIEWS, sqlglot_schema

PLACE_COLUMNS = frozenset({"state", "city", "country"})


@dataclass(frozen=True)
class Filter:
    view: str
    column: str
    literal: str


def string_filter(sql: str) -> Filter | None:
    """The first `column = 'text'` filter on a scoped view in the SQL of the LLM."""
    try:
        tree = qualify(sqlglot.parse_one(sql, read="bigquery"), schema=sqlglot_schema(), dialect="bigquery")
    except (SqlglotError, ValueError):
        return None
    for node in tree.find_all(exp.EQ):
        for side, other in ((node.left, node.right), (node.right, node.left)):
            if isinstance(side, exp.Column) and isinstance(other, exp.Literal) and other.is_string:
                select = node.find_ancestor(exp.Select)
                view = demographic.sources(select).get(side.table.lower()) if select else None
                if view in SCOPED_VIEWS:
                    return Filter(view, side.name.lower(), other.this)
    return None


def diagnostic_sql(found: Filter) -> str:
    """An aggregate of the values of the filter column. The SQL guard routes it like any query."""
    count = "COUNT(DISTINCT id)" if found.view == SCOPED_CUSTOMERS.name else "COUNT(*)"
    return f"SELECT {found.column}, {count} AS n FROM {found.view} GROUP BY {found.column} ORDER BY n DESC"


def notice(found: Filter | None, values: list[str]) -> Answer:
    if found is None:
        block = Notice(level="info", title="No data matches this question", body="Try a wider period or fewer filters.")
        return Answer(kind="notice", blocks=[block])
    word = "from" if found.column in PLACE_COLUMNS else f"with {found.column}"
    title = f'No orders {word} "{found.literal}"'
    by_lower = {value.lower(): value for value in values}
    close = difflib.get_close_matches(found.literal.lower(), list(by_lower), n=1, cutoff=0.6)
    if close:
        body = f"Did you mean {by_lower[close[0]]}?"
    elif values:
        body = f"Some values in your data: {', '.join(values[:5])}. Ask again with one of them."
    else:
        body = "Your data has no values for this filter. Try a different filter."
    return Answer(kind="notice", blocks=[Notice(level="info", title=title, body=body)])
