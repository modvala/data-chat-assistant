"""The Output guard (HLD 8.8): the last layer before the Executive sees an Answer.

It scans all text of the draft Answer for PII patterns, and it blocks a table that joins a
Customer ID to demographic columns. A hit replaces the Answer with a refusal `pii`.
The block validator, which drops the block types that only our code makes, is in `drafting`.
"""

import re
from collections.abc import Iterator

from dca.core.answer import ActionItems, Bullets, Heading, Kpi, Table, Text
from dca.core.schema import DEMOGRAPHIC_COLUMNS

PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(
        r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w-])"
        r"|(?<![\w-])\+\d{1,3}(?:[\s.-]\d{2,4}){3,4}(?![\w-])"
    ),
    "street_address": re.compile(
        r"\b\d{1,5}\s+(?:[A-Z][\w'-]*\s+){1,4}"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|Terrace)\b\.?"
    ),
    "coordinates": re.compile(r"-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}"),
}
CUSTOMER_ID_NAMES = frozenset({"user_id", "customer_id"})


def _strings(blocks: list) -> Iterator[str]:
    for block in blocks:
        if isinstance(block, Heading):
            yield block.text
        elif isinstance(block, Text):
            yield block.markdown
        elif isinstance(block, Bullets):
            yield from block.items
        elif isinstance(block, Kpi):
            yield from (value for value in (block.label, block.value, block.unit, block.delta, block.period) if value)
        elif isinstance(block, ActionItems):
            for item in block.items:
                yield from (value for value in (item.action, item.metric, item.owner) if value)
        elif isinstance(block, Table):
            yield from (column.name for column in block.columns)
            yield from (cell for row in block.rows for cell in row if isinstance(cell, str))


def check(blocks: list) -> str | None:
    """The reason of a hit, or None. The reason goes only to the trace."""
    for value in _strings(blocks):
        for reason, pattern in PATTERNS.items():
            if pattern.search(value):
                return reason
    for block in blocks:
        if isinstance(block, Table):
            names = {column.name.lower() for column in block.columns}
            has_id = bool(names & CUSTOMER_ID_NAMES) or any(column.type == "customer" for column in block.columns)
            if has_id and names & DEMOGRAPHIC_COLUMNS:
                return "id_with_demographics"
    return None
