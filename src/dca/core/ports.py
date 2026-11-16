"""The seven ports of HLD 4.4. The core reaches the outside only through them (P6).

This module imports no framework, warehouse, store or tracing SDK types.
"""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

Role = Literal["manager", "ceo"]


@dataclass(frozen=True)
class ExecutiveEntry:
    """One row of the access mapping (A1). `brands` is None for the CEO."""

    executive_id: str
    role: Role
    brands: tuple[str, ...] | None


@dataclass(frozen=True)
class Grant:
    """The Brand scope of the Executive of a Turn. For the CEO, `brands` holds all brands."""

    executive_id: str
    role: Role
    brands: tuple[str, ...]

    @property
    def all_brands(self) -> bool:
        return self.role == "ceo"


@dataclass(frozen=True)
class QueryResult:
    job_id: str
    columns: list[str]
    rows: list[list[Any]]
    bytes_processed: int


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


# --- Errors that adapters raise. The core maps them to typed reasons and notices.


class WarehouseError(Exception):
    """A query error that the LLM can fix: syntax, unknown column, wrong type."""


class WarehouseTransientError(Exception):
    """A 5xx or a timeout of the warehouse."""

    def __init__(self, message: str = "", job_id: str | None = None) -> None:
        super().__init__(message)
        self.job_id = job_id


class WarehouseCancelled(Exception):
    """The job was cancelled."""


class LLMTransientError(Exception):
    """A 429, a 5xx or a timeout of the LLM."""

    def __init__(self, status: int, retry_after: float | None = None) -> None:
        super().__init__(f"LLM status {status}")
        self.status = status
        self.retry_after = retry_after


class LLMUnavailable(Exception):
    """The LLM failed after all retries."""


# --- Ports


class LLMClient(Protocol):
    def generate(self, prompt: str, *, model: str, system: str = "", json_schema: dict | None = None) -> LLMResult: ...


class Warehouse(Protocol):
    def dry_run(self, sql: str, params: dict[str, Sequence[str]]) -> int: ...

    def run(
        self, sql: str, params: dict[str, Sequence[str]], *, max_bytes: int, timeout_s: float, job_id: str
    ) -> QueryResult: ...

    def cancel(self, job_id: str) -> None: ...


class KnowledgeStore(Protocol):
    def schema(self) -> str: ...


class Span(Protocol):
    def set(self, key: str, value: Any) -> None: ...


class Tracer(Protocol):
    def span(self, name: str, **attributes: Any) -> AbstractContextManager[Span]: ...

    def log(self, event: str, **fields: Any) -> None: ...

    def current_trace_id(self) -> str: ...

    def read(self, trace_id: str) -> list[dict]: ...


class SessionStore(Protocol):
    def load(self, session_id: str) -> Any | None: ...

    def save(self, state: Any) -> None: ...


class ConfigStore(Protocol):
    def access(self, executive_id: str) -> ExecutiveEntry | None: ...

    def executive_ids(self) -> list[str]: ...


@dataclass
class SavedReport:
    report_id: str
    owner_id: str
    created_session_id: str
    title: str
    body: str
    sql: list[str]
    customer_ids: list[str]
    created_at: datetime
    deleted_at: datetime | None = None
    delete_batch_id: str | None = None


@dataclass(frozen=True)
class ReportFilter:
    customer_ids: tuple[str, ...] = ()
    created_session_id: str | None = None


@dataclass(frozen=True)
class DeleteBatch:
    batch_id: str
    executive_id: str
    report_ids: tuple[str, ...]
    deleted_at: datetime
    undo_until: datetime
    restored: bool = False


@dataclass(frozen=True)
class AuditEntry:
    executive_id: str
    action: Literal["delete", "undo"]
    batch_id: str
    report_ids: tuple[str, ...]
    trace_id: str
    at: datetime
    entry_id: str = field(default="")


class ReportStore(Protocol):
    def save(self, report: SavedReport) -> None: ...

    def find(self, owner_id: str, report_filter: ReportFilter | None = None) -> list[SavedReport]: ...

    def soft_delete(self, ids: Sequence[str], actor: str, undo_until: datetime, at: datetime) -> DeleteBatch: ...

    def last_batch(self, actor: str) -> DeleteBatch | None: ...

    def restore(self, batch_id: str, actor: str) -> list[str]: ...

    def audit(self, entry: AuditEntry) -> None: ...

    def audit_entries(self, actor: str) -> Iterator[AuditEntry]: ...
