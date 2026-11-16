"""The run-time state of one Turn. It lives only for the Turn. The session state keeps the rest."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dca.config import Settings
from dca.core.answer import RefusalReason
from dca.core.ports import Grant, Tracer, Warehouse
from dca.core.state import SessionState, SqlAttempt

Progress = Callable[[str, dict[str, Any]], None]


class TurnStop(Exception):
    """Stops the Agent loop. Our code then makes the Answer: a refusal, or a notice."""

    def __init__(self, reason: RefusalReason, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class QueryRun:
    query_id: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    bytes_scanned: int
    customer_columns: tuple[str, ...] = ()


@dataclass
class TurnContext:
    grant: Grant
    session: SessionState
    trace_id: str
    settings: Settings
    warehouse: Warehouse
    tracer: Tracer
    progress: Progress
    queries: dict[str, QueryRun] = field(default_factory=dict)
    attempts: list[SqlAttempt] = field(default_factory=list)

    def next_query_id(self) -> str:
        return f"q{len(self.queries) + 1}"

    @property
    def bytes_scanned(self) -> int:
        return sum(query.bytes_scanned for query in self.queries.values())
