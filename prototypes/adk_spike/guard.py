"""PROTOTYPE, throwaway. A minimal PII guard with no ADK imports (P6).

The real SQL guard will be larger. This one only proves that plain Python
code can make the decision and that ADK calls it before the tool runs.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

PII_COLUMNS = {
    "email",
    "first_name",
    "last_name",
    "street_address",
    "postal_code",
    "latitude",
    "longitude",
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def check_sql(sql: str) -> Decision:
    try:
        tree = sqlglot.parse_one(sql, dialect="bigquery")
    except sqlglot.errors.ParseError as error:
        return Decision(False, f"parse_error: {error}")
    if not isinstance(tree, exp.Select):
        return Decision(False, "not_select")
    used = {column.name.lower() for column in tree.find_all(exp.Column)}
    pii = sorted(used & PII_COLUMNS)
    if pii:
        return Decision(False, f"pii: {', '.join(pii)}")
    return Decision(True, "ok")
