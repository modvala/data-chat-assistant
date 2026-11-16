"""The tools of HLD 7, as plain core functions. The framework adapter wraps them.

| Tool | Side-effect class |
| --- | --- |
| describe_schema | read |
| run_query | read, with the SQL guard |
| save_report | write-own |
| list_reports | read-own |
| plan_delete | plan: changes nothing, the Confirmation gate deletes |
"""

import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypeVar

from dca.core import backoff, confirmation, demographic, diagnostic, reports, sql_guard
from dca.core.answer import Answer, Notice
from dca.core.ports import Grant, KnowledgeStore, WarehouseCancelled, WarehouseError, WarehouseTransientError
from dca.core.state import SqlAttempt
from dca.core.turn import QueryRun, TurnCancelled, TurnContext, TurnFinish, TurnStop


T = TypeVar("T")


def describe_schema(knowledge: KnowledgeStore) -> dict[str, Any]:
    return {"schema": knowledge.schema()}


def save_report(turn: TurnContext, title: str, grant: Grant) -> dict[str, Any]:
    """Saves the last Answer. The owner is the Executive of the Turn, never a value from the LLM."""
    assert turn.reports is not None
    report = reports.save(
        turn.session, owner_id=grant.executive_id, title=title, reports=turn.reports, tracer=turn.tracer, now=turn.now
    )
    if report is None:
        return {"error": "There is no earlier Answer to save."}
    return {"saved": True, "title": report.title}


def plan_delete(
    turn: TurnContext, grant: Grant, *, customer_ids: list[str], this_conversation: bool, customer_name: str
) -> dict[str, Any]:
    """Finds the own Saved Reports that match and makes a preview. It changes nothing (ADR 0002)."""
    assert turn.reports is not None
    if not customer_ids and not this_conversation:
        if customer_name.strip():
            notice = Notice(
                level="info",
                title="I need the Customer ID",
                body="Saved Reports record Customers by ID only. Type the request again with the Customer ID, "
                "for example: Delete all reports mentioning Customer 4521.",
            )
            raise TurnFinish(Answer(kind="notice", blocks=[notice]), "answered")
        return {"error": "Give customer_ids, or set this_conversation to true."}
    answer, pending = confirmation.plan(
        turn.reports,
        owner_id=grant.executive_id,
        session_id=turn.session.session_id,
        customer_ids=customer_ids,
        this_conversation=this_conversation,
        now=turn.now,
        settings=turn.settings,
    )
    turn.session.pending = pending
    with turn.tracer.span("confirmation", state="pending" if pending else "no_match") as span:
        span.set("count", len(pending.report_ids) if pending else 0)
    raise TurnFinish(answer, "pending" if pending else "answered")


def list_reports(turn: TurnContext, grant: Grant) -> dict[str, Any]:
    assert turn.reports is not None
    own = turn.reports.find(grant.executive_id)
    return {"reports": [{"title": r.title, "created": r.created_at.date().isoformat()} for r in own]}


def _guard(turn: TurnContext, sql: str, grant: Grant) -> sql_guard.Verdict:
    settings = turn.settings
    with turn.tracer.span("guard.sql") as span:
        verdict = sql_guard.check(
            sql,
            grant,
            source_dataset=settings.warehouse.source_dataset,
            sql_limit=settings.limits.sql_limit,
            threshold_view=turn.threshold.view,
            threshold_k=settings.warehouse.threshold_k,
        )
        span.set("decision", "allowed" if isinstance(verdict, sql_guard.Allowed) else "blocked")
        if isinstance(verdict, sql_guard.Blocked):
            span.set("reason", verdict.reason)
            span.set("detail", verdict.detail)
        else:
            span.set("route", verdict.route)
    return verdict


def _view_missing(error: Exception) -> bool:
    text = str(error).lower()
    return demographic.THRESHOLD_VIEW in text and ("not found" in text or "expired" in text)


def failed_attempts(turn: TurnContext) -> int:
    """The SQL corrections of the Turn: each failed attempt gets one (AC-R5.1)."""
    return sum(1 for attempt in turn.attempts if attempt.error)


def _fail(turn: TurnContext, attempt: SqlAttempt, error: str, llm_text: str) -> dict[str, Any]:
    """Records a failed attempt. After the last correction, the Turn ends with an error notice."""
    attempt.error = error
    if failed_attempts(turn) > turn.settings.budget.corrections:
        notice = Notice(
            level="error",
            title="I could not make a working query",
            body="Please ask the question in a different way. Your session continues.",
            trace_id=turn.trace_id,
        )
        turn.tracer.log("sql.corrections_used", attempts=len(turn.attempts))
        raise TurnFinish(Answer(kind="notice", blocks=[notice]), "failed", stop_limit="corrections")
    return {"error": llm_text}


def run_query(turn: TurnContext, sql: str, grant: Grant) -> dict[str, Any]:
    settings = turn.settings
    turn.check_cancel()
    failures = failed_attempts(turn)
    attempt = SqlAttempt(sql=sql)
    turn.attempts.append(attempt)
    with turn.tracer.span("tool.run_query", attempt=len(turn.attempts), correction=failures):
        if failures:
            turn.progress("correction", {"attempt": failures + 1, "of": settings.budget.corrections + 1})
        turn.progress("dry_run", {})
        while True:
            verdict = _guard(turn, sql, grant)
            if isinstance(verdict, sql_guard.Blocked):
                if verdict.refusal:
                    attempt.error = verdict.reason
                    raise TurnStop(verdict.reason)  # type: ignore[arg-type]
                return _fail(turn, attempt, verdict.reason, verdict.llm_text)
            attempt.final_sql = verdict.sql

            with turn.tracer.span("bq.dry_run") as span:
                try:
                    estimate = _with_retry(turn, lambda _job: turn.warehouse.dry_run(verdict.sql, verdict.params), "")
                except WarehouseError as error:
                    span.set("error", str(error))
                    if verdict.route == "threshold_view" and _view_missing(error):
                        # ADR 0005: an expired view in the sandbox. Use the HAVING fallback from now on.
                        turn.threshold.view = None
                        turn.tracer.log("threshold_view.unavailable")
                        continue
                    return _fail(turn, attempt, str(error), f"The query failed in the dry run. Fix it. Detail: {error}")
                span.set("bytes", estimate)
                if turn.budget:
                    try:
                        turn.budget.before_query(estimate)
                    except TurnStop:
                        span.set("over_limit", True)
                        raise
            break

        turn.progress("query", {})
        query_id = turn.next_query_id()
        with turn.tracer.span("bq.query", sql=verdict.sql) as span:
            try:
                result = _with_retry(
                    turn,
                    lambda job_id: turn.warehouse.run(
                        verdict.sql,
                        verdict.params,
                        max_bytes=settings.budget.query_bytes,
                        timeout_s=settings.timeout.bq_job_s,
                        job_id=job_id,
                    ),
                    f"dca-{turn.trace_id}-{query_id}-{len(turn.attempts)}",
                )
            except WarehouseError as error:
                span.set("error", str(error))
                return _fail(turn, attempt, str(error), f"The query failed. Fix it. Detail: {error}")
            except WarehouseCancelled:
                span.set("cancelled", True)
                raise TurnCancelled() from None
            finally:
                turn.running_job = None
            if turn.budget:
                turn.budget.add_bytes(result.bytes_processed)
            rows = [[jsonable(value) for value in row] for row in result.rows]
            span.set("bytes", result.bytes_processed)
            span.set("rows", len(rows))
            span.set("columns", result.columns)
        if not rows:
            _empty_result(turn, sql, grant, demographic_route=verdict.route != "scoped")

    turn.queries[query_id] = QueryRun(
        query_id=query_id,
        sql=verdict.sql,
        columns=result.columns,
        rows=rows,
        bytes_scanned=result.bytes_processed,
        customer_columns=verdict.customer_columns,
        llm_sql=sql,
    )
    return {
        "query_id": query_id,
        "columns": result.columns,
        "rows": rows[: settings.limits.rows_to_llm],
        "row_count": len(rows),
    }


def _with_retry(turn: TurnContext, call: Callable[[str], T], job_id: str) -> T:
    """A BigQuery 5xx or timeout gets `bq_retries` retries with backoff (V8). Our code cancels the
    timed-out job first, so that it does not run on (V9). Each retry has a new job ID."""
    retry = turn.settings.retry
    for attempt in range(retry.bq_retries + 1):
        try:
            turn.check_cancel()
            current = f"{job_id}-r{attempt}" if job_id and attempt else job_id
            turn.running_job = current or None
            return call(current)
        except WarehouseTransientError as error:
            if error.job_id:
                turn.warehouse.cancel(error.job_id)
            turn.tracer.log("bq.transient_error", attempt=attempt + 1, error=str(error)[:100])
            if attempt == retry.bq_retries:
                raise
            wait = backoff.delay(attempt + 1, None, retry)
            turn.progress("retry", {"seconds": max(1, round(wait))})
            time.sleep(wait)
    raise AssertionError("unreachable")


def _empty_result(turn: TurnContext, llm_sql: str, grant: Grant, *, demographic_route: bool) -> None:
    """A query with 0 rows: find the cause, then end the Turn (HLD 15.1).

    A filter value that is not in the data gets an info notice with a next step. Otherwise, on a
    demographic route, the threshold hid all groups: a refusal `threshold` (ADR 0005).
    """
    found = diagnostic.string_filter(llm_sql)
    exists = False
    values: list[str] = []
    if found is not None:
        with turn.tracer.span("bq.diagnostic", column=found.column) as span:
            exists = bool(_diagnostic_values(turn, grant, diagnostic.existence_sql(found), "exists"))
            if not exists:
                values = _diagnostic_values(turn, grant, diagnostic.diagnostic_sql(found), "values")
            span.set("exists", exists)
            span.set("values", len(values))
    suggestion = diagnostic.close_value(found, values) if found else None
    if demographic_route and suggestion is None:
        # The value exists, or a small group can hide it: never guess a typo here (ADR 0005).
        raise TurnStop("threshold")
    raise TurnFinish(diagnostic.notice(found, values, exists=exists), "answered")


def _diagnostic_values(turn: TurnContext, grant: Grant, sql: str, step: str) -> list[str]:
    """The values of the first column of a diagnostic query, through the SQL guard. Best effort."""
    verdict = sql_guard.check(
        sql,
        grant,
        source_dataset=turn.settings.warehouse.source_dataset,
        sql_limit=turn.settings.limits.sql_limit,
        threshold_view=turn.threshold.view,
        threshold_k=turn.settings.warehouse.threshold_k,
    )
    if not isinstance(verdict, sql_guard.Allowed):
        return []
    try:
        result = turn.warehouse.run(
            verdict.sql,
            verdict.params,
            max_bytes=turn.settings.budget.query_bytes,
            timeout_s=turn.settings.timeout.bq_job_s,
            job_id=f"dca-diag-{turn.trace_id}-{len(turn.attempts)}-{step}",
        )
    except (WarehouseError, WarehouseTransientError):
        return []
    return [str(row[0]) for row in result.rows if row[0] is not None]


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
