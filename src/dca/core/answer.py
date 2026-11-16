"""The channel-neutral Answer model of cli.md: kind, blocks and Provenance.

The LLM makes only `heading`, `text`, `bullets`, `kpi` and `action_items` blocks.
Our code makes `table`, `notice`, `refusal`, `confirmation`, `result`, `sql` and `trace` blocks (DS3).
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Source = Literal["llm", "code"]
RefusalReason = Literal["pii", "scope", "not_analysis", "threshold", "budget"]

LLM_BLOCK_TYPES = frozenset({"heading", "text", "bullets", "kpi", "action_items"})


class Heading(BaseModel):
    type: Literal["heading"] = "heading"
    source: Source = "llm"
    text: str


class Text(BaseModel):
    type: Literal["text"] = "text"
    source: Source = "llm"
    markdown: str


class Bullets(BaseModel):
    type: Literal["bullets"] = "bullets"
    source: Source = "llm"
    items: list[str]


class Kpi(BaseModel):
    type: Literal["kpi"] = "kpi"
    source: Source = "llm"
    label: str
    value: str
    unit: str | None = None
    delta: str | None = None
    period: str | None = None
    good_direction: Literal["up", "down"] = "up"


class ActionItem(BaseModel):
    action: str
    metric: str
    owner: str | None = None


class ActionItems(BaseModel):
    type: Literal["action_items"] = "action_items"
    source: Source = "llm"
    items: list[ActionItem]


class Column(BaseModel):
    name: str
    type: str = "string"
    unit: str | None = None


class Table(BaseModel):
    type: Literal["table"] = "table"
    source: Source = "code"
    query_id: str
    columns: list[Column]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool = False


class Notice(BaseModel):
    type: Literal["notice"] = "notice"
    source: Source = "code"
    level: Literal["info", "warning", "error"]
    title: str
    body: str = ""
    trace_id: str = ""


class Refusal(BaseModel):
    type: Literal["refusal"] = "refusal"
    source: Source = "code"
    reason: RefusalReason
    title: str
    body: str
    suggestion: str | None = None


class ConfirmationItem(BaseModel):
    id: str
    title: str
    date: str


class Confirmation(BaseModel):
    type: Literal["confirmation"] = "confirmation"
    source: Source = "code"
    action: str
    description: str
    items: list[ConfirmationItem]
    count: int
    reply_text: str
    expires_at: datetime
    undo_window_h: int


class Result(BaseModel):
    type: Literal["result"] = "result"
    source: Source = "code"
    action: Literal["deleted", "restored"]
    count: int
    undo_until: datetime | None = None


class SqlView(BaseModel):
    """The SQL of the last Answer, for /sql (cli.md C14). Only our code makes it."""

    type: Literal["sql"] = "sql"
    source: Source = "code"
    sql: str
    bytes_scanned: int = 0
    row_count: int | None = None
    error: str = ""


class TraceRow(BaseModel):
    label: str
    status: Literal["ok", "error", "refusal", "info"]
    detail: str = ""
    duration_ms: float = 0


class TraceView(BaseModel):
    """The span tree of one Turn, for /trace (cli.md C15). Only our code makes it."""

    type: Literal["trace"] = "trace"
    source: Source = "code"
    trace_id: str
    started: datetime
    duration_ms: float
    outcome: str
    rows: list[TraceRow]


class TableRef(BaseModel):
    """A place for a table in an LLM draft. Our code fills it from the query rows."""

    type: Literal["table"] = "table"
    query_id: str


Block = Annotated[
    Heading
    | Text
    | Bullets
    | Kpi
    | ActionItems
    | Table
    | Notice
    | Refusal
    | Confirmation
    | Result
    | SqlView
    | TraceView,
    Field(discriminator="type"),
]


class Provenance(BaseModel):
    brand_scope: list[str] = Field(default_factory=list)
    all_brands: bool = False
    assumptions: list[str] = Field(default_factory=list)
    trio_ids: list[str] = Field(default_factory=list)
    metric_variant: str | None = None
    sql: list[str] = Field(default_factory=list)
    bytes_scanned: int = 0
    corrections: int = 0
    model: str = ""
    fallback_used: bool = False
    persona_version: str = ""
    trace_id: str = ""


class Answer(BaseModel):
    kind: Literal["answer", "notice", "confirmation"]
    blocks: list[Block]
    provenance: Provenance = Field(default_factory=Provenance)
    report: bool = False
    awaiting_confirmation: bool = False
