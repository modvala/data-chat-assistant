"""Session state. The Turn API loads it at the start of a Turn and saves it at the end (P21)."""

from datetime import datetime

from pydantic import BaseModel, Field

from dca.core.answer import Answer


class QueryHandle(BaseModel):
    """What the next Turns know about a query: no rows, only the shape (HLD 9.4)."""

    query_id: str
    trace_id: str
    sql: str  # the final SQL after the Brand scope rewrite, for /sql
    llm_sql: str = ""  # the SQL that the LLM wrote, for the context of the next Turns
    columns: list[str]
    row_count: int
    bytes_scanned: int
    customer_ids: list[str] = Field(default_factory=list)


class SqlAttempt(BaseModel):
    sql: str
    final_sql: str = ""
    error: str = ""


class TurnRecord(BaseModel):
    trace_id: str
    message: str
    answer: Answer
    outcome: str
    query_ids: list[str] = Field(default_factory=list)


class PendingConfirmation(BaseModel):
    executive_id: str
    session_id: str
    report_ids: list[str]
    ids_hash: str
    expected_reply: str
    expires_at: datetime
    customer_ids: list[str] = Field(default_factory=list)
    created_session_id: str | None = None


class SessionState(BaseModel):
    session_id: str
    executive_id: str
    turns: list[TurnRecord] = Field(default_factory=list)
    handles: list[QueryHandle] = Field(default_factory=list)
    last_attempts: list[SqlAttempt] = Field(default_factory=list)
    pending: PendingConfirmation | None = None

    @property
    def last_answer(self) -> Answer | None:
        return self.turns[-1].answer if self.turns else None
