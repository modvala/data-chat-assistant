"""Turns the LLM draft into an Answer. Our code makes each `table` block from the query rows.

The block validator (`build_blocks`) keeps only the block types that the LLM may make (DS3):
heading, text, bullets, kpi, action_items, and a table reference. It drops all other types.
"""

import json
import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from dca.core.answer import (
    LLM_BLOCK_TYPES,
    ActionItems,
    Answer,
    Bullets,
    Column,
    Heading,
    Kpi,
    Provenance,
    Table,
    Text,
)
from dca.core import messages, output_guard
from dca.core.turn import QueryRun, TurnContext

_LLM_MODELS: dict[str, Any] = {
    "heading": TypeAdapter(Heading),
    "text": TypeAdapter(Text),
    "bullets": TypeAdapter(Bullets),
    "kpi": TypeAdapter(Kpi),
    "action_items": TypeAdapter(ActionItems),
}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_MONEY_WORDS = ("revenue", "sale_price", "spend", "price", "cost", "sales", "amount", "aov", "value")


def parse_draft(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The LLM answers with `{"blocks": [...], "assumptions": [...]}`. Other text becomes one `text` block."""
    stripped = _FENCE.sub("", text.strip())
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return ([{"type": "text", "markdown": text.strip()}] if text.strip() else []), []
    if isinstance(data, dict) and isinstance(data.get("blocks"), list):
        blocks = [block for block in data["blocks"] if isinstance(block, dict)]
        assumptions = [str(item) for item in data.get("assumptions") or [] if isinstance(item, str | int | float)]
        return blocks, assumptions
    return [{"type": "text", "markdown": text.strip()}], []


def build_blocks(draft: list[dict[str, Any]], turn: TurnContext) -> tuple[list, list[str]]:
    """Returns the blocks and the types of the dropped blocks."""
    blocks: list = []
    dropped: list[str] = []
    for raw in draft:
        kind = str(raw.get("type", ""))
        if kind == "table":
            query = turn.queries.get(str(raw.get("query_id", "")))
            if query is None:
                dropped.append("table")
                continue
            blocks.append(table_block(query, turn.settings.limits.table_rows_shown))
        elif kind in LLM_BLOCK_TYPES:
            try:
                blocks.append(_LLM_MODELS[kind].validate_python({**raw, "source": "llm"}))
            except ValidationError:
                dropped.append(kind)
        else:
            dropped.append(kind or "unknown")
    return blocks, dropped


def table_block(query: QueryRun, max_rows: int) -> Table:
    columns = [Column(name=name, type=_column_type(name, query)) for name in query.columns]
    return Table(
        query_id=query.query_id,
        columns=columns,
        rows=query.rows[:max_rows],
        total_rows=len(query.rows),
        truncated=len(query.rows) > max_rows,
    )


def _column_type(name: str, query: QueryRun) -> str:
    if name in query.customer_columns:
        return "customer"
    index = query.columns.index(name)
    values = [row[index] for row in query.rows if row[index] is not None]
    if values and all(isinstance(value, int | float) and not isinstance(value, bool) for value in values):
        if any(word in name.lower() for word in _MONEY_WORDS):
            return "money"
        return "int" if all(isinstance(value, int) for value in values) else "number"
    return "string"


def provenance(turn: TurnContext, *, model: str, fallback_used: bool = False) -> Provenance:
    return Provenance(
        brand_scope=list(turn.grant.brands),
        all_brands=turn.grant.all_brands,
        sql=[query.sql for query in turn.queries.values()],
        bytes_scanned=turn.bytes_scanned,
        corrections=sum(1 for attempt in turn.attempts if attempt.error),
        model=model,
        fallback_used=fallback_used,
        persona_version=turn.settings.persona_version,
        trace_id=turn.trace_id,
    )


def answer_from_draft(text: str, turn: TurnContext, *, model: str, fallback_used: bool = False) -> Answer:
    draft, assumptions = parse_draft(text)
    blocks, dropped = build_blocks(draft, turn)
    with turn.tracer.span("guard.output") as span:
        span.set("dropped_blocks", dropped)
        reason = output_guard.check(blocks + [Text(markdown=item) for item in assumptions])
        span.set("decision", "blocked" if reason else "allowed")
        span.set("reason", reason)
        if not reason:
            # V20: the trace keeps the first rows of each table, only after the Output guard passed them.
            for block in blocks:
                if isinstance(block, Table):
                    span.set(f"rows.{block.query_id}", block.rows[: turn.settings.limits.trace_rows])
    if reason:
        return Answer(
            kind="notice",
            blocks=[messages.refusal("pii")],
            provenance=provenance(turn, model=model, fallback_used=fallback_used),
        )
    if not blocks:
        blocks = [Text(source="code", markdown="I have no answer for this question. Please ask it in a different way.")]
    checked = provenance(turn, model=model, fallback_used=fallback_used)
    checked.assumptions = assumptions
    return Answer(kind="answer", blocks=blocks, provenance=checked, report=turn.intent == "report")
