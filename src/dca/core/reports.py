"""Saved Reports (HLD 7, 10.5). `/save` and `/list` call the same code as the tools.

| Tool | Side-effect class | Guard |
| --- | --- | --- |
| save_report | write-own | The owner is the Executive of the Turn |
| list_reports | read-own | Owner filter in code |
"""

import uuid
from datetime import datetime

from dca.core.answer import Answer, Column, Heading, Notice, Table
from dca.core.ports import ReportStore, SavedReport, Tracer
from dca.core.state import SessionState, TurnRecord

TITLE_CHARS = 60


def last_answer(state: SessionState) -> TurnRecord | None:
    """The last Turn that gave an Answer (not a refusal or a notice)."""
    return next(
        (record for record in reversed(state.turns) if record.outcome == "answered" and record.answer.kind == "answer"),
        None,
    )


def customer_ids(state: SessionState, record: TurnRecord) -> list[str]:
    """The Customer IDs from the result rows of the queries of the Answer. The LLM does not make this list."""
    used = set(record.query_ids)
    return sorted({cid for handle in state.handles if handle.query_id in used for cid in handle.customer_ids})


def save(
    state: SessionState, *, owner_id: str, title: str, reports: ReportStore, tracer: Tracer, now: datetime
) -> SavedReport | None:
    record = last_answer(state)
    if record is None:
        return None
    heading = next((block.text for block in record.answer.blocks if isinstance(block, Heading)), None)
    report = SavedReport(
        report_id=uuid.uuid4().hex[:12],
        owner_id=owner_id,
        created_session_id=state.session_id,
        title=(title.strip() or heading or record.message)[:TITLE_CHARS],
        body=record.answer.model_dump_json(),
        sql=list(record.answer.provenance.sql),
        customer_ids=customer_ids(state, record),
        created_at=now,
    )
    with tracer.span("report.save", report_id=report.report_id, customers=len(report.customer_ids)):
        reports.save(report)
    return report


def saved_notice(report: SavedReport | None) -> Answer:
    if report is None:
        notice = Notice(level="info", title="There is no Answer to save", body="Ask a question first, then type /save.")
    else:
        notice = Notice(level="info", title=f'Saved "{report.title}"', body="Type /list to see your Saved Reports.")
    return Answer(kind="notice", blocks=[notice])


def list_answer(reports: list[SavedReport], title: str = "Your Saved Reports") -> Answer:
    if not reports:
        notice = Notice(level="info", title="You have no Saved Reports", body="Type /save after an Answer to keep it.")
        return Answer(kind="notice", blocks=[notice])
    table = Table(
        query_id="saved_reports",
        columns=[Column(name="title"), Column(name="created")],
        rows=[[report.title, report.created_at.date().isoformat()] for report in reports],
        total_rows=len(reports),
    )
    return Answer(kind="answer", blocks=[Heading(source="code", text=title), table])
