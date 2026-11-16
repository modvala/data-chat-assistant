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


CLOSE_MATCH = 0.8  # "Califronia" and "California": 0.9. "Boston" and "Houston": 0.67, no suggestion.


def _count(found: Filter) -> str:
    return "COUNT(DISTINCT id)" if found.view == SCOPED_CUSTOMERS.name else "COUNT(*)"


def existence_sql(found: Filter) -> str:
    """Is the exact value in the data? An aggregate, so the SQL guard routes it like any query."""
    value = exp.Literal.string(found.literal).sql(dialect="bigquery")
    return (
        f"SELECT {found.column}, {_count(found)} AS n FROM {found.view} "
        f"WHERE {found.column} = {value} GROUP BY {found.column}"
    )


def diagnostic_sql(found: Filter) -> str:
    """An aggregate of the most frequent values of the filter column."""
    return f"SELECT {found.column}, {_count(found)} AS n FROM {found.view} GROUP BY {found.column} ORDER BY n DESC"


def close_value(found: Filter, values: list[str]) -> str | None:
    by_lower = {value.lower(): value for value in values}
    close = difflib.get_close_matches(found.literal.lower(), list(by_lower), n=1, cutoff=CLOSE_MATCH)
    return by_lower[close[0]] if close else None


def notice(found: Filter | None, values: list[str], *, exists: bool = False) -> Answer:
    if found is None or exists:
        block = Notice(level="info", title="No data matches this question", body="Try a wider period or fewer filters.")
        return Answer(kind="notice", blocks=[block])
    word = "from" if found.column in PLACE_COLUMNS else f"with {found.column}"
    title = f'No orders {word} "{found.literal}"'
    close = close_value(found, values)
    if close:
        body = f"Did you mean {close}?"
    elif values:
        body = f"Some values in your data: {', '.join(values[:5])}. Ask again with one of them."
    else:
        body = "Your data has no values for this filter. Try a different filter."
    return Answer(kind="notice", blocks=[Notice(level="info", title=title, body=body)])
