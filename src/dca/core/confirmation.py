"""Destructive operations (HLD 10, ADR 0002): the LLM only plans, our code deletes.

`plan_delete` finds the own Saved Reports that match and makes a pending confirmation. It
changes nothing. Only the Confirmation gate, which reads the next message of the Executive
before the LLM, can delete.
"""

import hashlib
from datetime import datetime, timedelta

from dca.config import Settings
from dca.core.answer import Answer, Confirmation, ConfirmationItem, Notice, Provenance
from dca.core.ports import ReportFilter, ReportStore, SavedReport
from dca.core.state import PendingConfirmation


def ids_hash(report_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(report_ids)).encode()).hexdigest()


def expected_reply(count: int) -> str:
    """The friction grows with the blast radius (AC-R3.1)."""
    return "yes" if count == 1 else f"delete {count}"


def report_filter(pending: PendingConfirmation) -> ReportFilter:
    return ReportFilter(customer_ids=tuple(pending.customer_ids), created_session_id=pending.created_session_id)


def matching(reports: ReportStore, owner_id: str, pending: PendingConfirmation) -> list[SavedReport]:
    """The own Saved Reports that the request matches now. The owner filter is always on (AC-R3.2)."""
    return reports.find(owner_id, report_filter(pending))


def describe(pending: PendingConfirmation) -> str:
    if pending.customer_ids:
        ids = ", ".join(pending.customer_ids)
        return f"These reports mention Customer {ids}:" if len(pending.customer_ids) == 1 else f"These reports mention Customers {ids}:"
    return "These reports were made in this conversation:"


def no_match(pending: PendingConfirmation) -> Answer:
    if pending.customer_ids:
        title = f"No Saved Reports of yours mention Customer {', '.join(pending.customer_ids)}"
    else:
        title = "You made no Saved Reports in this conversation"
    return Answer(kind="notice", blocks=[Notice(level="info", title=title, body="Nothing was deleted.")])


def plan(
    reports: ReportStore,
    *,
    owner_id: str,
    session_id: str,
    customer_ids: list[str],
    this_conversation: bool,
    now: datetime,
    settings: Settings,
) -> tuple[Answer, PendingConfirmation | None]:
    """The preview Answer and the pending confirmation (or None when nothing matches)."""
    draft = PendingConfirmation(
        executive_id=owner_id,
        session_id=session_id,
        report_ids=[],
        ids_hash="",
        expected_reply="",
        expires_at=now,
        customer_ids=sorted({str(cid).strip() for cid in customer_ids if str(cid).strip()}),
        created_session_id=session_id if this_conversation else None,
    )
    return preview(reports, draft, now=now, settings=settings)


def preview(
    reports: ReportStore, draft: PendingConfirmation, *, now: datetime, settings: Settings
) -> tuple[Answer, PendingConfirmation | None]:
    found = matching(reports, draft.executive_id, draft)
    if not found:
        return no_match(draft), None
    ids = sorted(report.report_id for report in found)
    pending = draft.model_copy(
        update={
            "report_ids": ids,
            "ids_hash": ids_hash(ids),
            "expected_reply": expected_reply(len(ids)),
            "expires_at": now + timedelta(seconds=settings.confirmation.ttl_s),
        }
    )
    block = Confirmation(
        action="delete",
        description=describe(pending),
        items=[
            ConfirmationItem(id=report.report_id, title=report.title, date=report.created_at.date().isoformat())
            for report in found[: settings.display.preview_max_items]
        ],
        count=len(ids),
        reply_text=pending.expected_reply,
        expires_at=pending.expires_at,
        undo_window_h=settings.confirmation.undo_window_h,
    )
    return Answer(kind="confirmation", blocks=[block], provenance=Provenance(), awaiting_confirmation=True), pending


def is_exact_reply(text: str, pending: PendingConfirmation) -> bool:
    return " ".join(text.split()).lower() == pending.expected_reply
