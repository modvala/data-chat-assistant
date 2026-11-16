"""The run-time state of one Turn. It lives only for the Turn. The session state keeps the rest."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dca.config import Settings
from dca.core.answer import Answer, RefusalReason
from dca.core.ports import Grant, ReportStore, Tracer, Warehouse
from dca.core.state import SessionState, SqlAttempt

if TYPE_CHECKING:
    from dca.core.budget import TurnBudget

Progress = Callable[[str, dict[str, Any]], None]


class TurnStop(Exception):
    """Stops the Agent loop. Our code then makes the Answer: a refusal, or a notice."""

    def __init__(self, reason: RefusalReason, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class TurnFinish(Exception):
    """Ends the Agent loop with an Answer that our code made, for example a delete preview."""

    def __init__(self, answer: Answer, outcome: str, stop_limit: str | None = None) -> None:
        super().__init__(outcome)
        self.answer = answer
        self.outcome = outcome
        self.stop_limit = stop_limit


class TurnCancelled(Exception):
    """The Executive pressed Ctrl+C during the Turn."""


@dataclass
class QueryRun:
    query_id: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    bytes_scanned: int
    customer_columns: tuple[str, ...] = ()
    llm_sql: str = ""

    @property
    def customer_ids(self) -> list[str]:
        """The Customer IDs in the result rows (HLD 10.5)."""
        indexes = [self.columns.index(name) for name in self.customer_columns if name in self.columns]
        return sorted({str(row[i]) for row in self.rows for i in indexes if row[i] is not None})


@dataclass(frozen=True)
class DateRange:
    """Today and the min and max order date of the data (HLD 9.3)."""

    today: str
    min_date: str
    max_date: str


@dataclass
class ThresholdState:
    """The full name of the threshold view, or None when it is not available (ADR 0005)."""

    view: str | None


@dataclass
class TurnContext:
    grant: Grant
    session: SessionState
    trace_id: str
    settings: Settings
    warehouse: Warehouse
    tracer: Tracer
    progress: Progress
    threshold: ThresholdState = field(default_factory=lambda: ThresholdState(None))
    intent: str = "analysis"
    dates: DateRange | None = None
    reports: ReportStore | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    budget: "TurnBudget | None" = None
    cancelled: bool = False
    running_job: str | None = None
    stop_limit: str | None = None  # the budget limit that stopped the Turn, for the trace
    run: int = 1  # 1 for the main model, 2 for the fallback model. Each BigQuery job ID has it.

    def check_cancel(self) -> None:
        if self.cancelled:
            raise TurnCancelled()
    queries: dict[str, QueryRun] = field(default_factory=dict)
    attempts: list[SqlAttempt] = field(default_factory=list)

    def next_query_id(self) -> str:
        return f"q{len(self.queries) + 1}"

    @property
    def bytes_scanned(self) -> int:
        return sum(query.bytes_scanned for query in self.queries.values())
