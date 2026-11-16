"""The tools of HLD 7, as plain core functions. The framework adapter wraps them.

| Tool | Side-effect class |
| --- | --- |
| describe_schema | read |
| run_query | read, with the SQL guard |
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from dca.core import demographic, sql_guard
from dca.core.ports import Grant, KnowledgeStore, WarehouseError
from dca.core.state import SqlAttempt
from dca.core.turn import QueryRun, TurnContext, TurnStop


def describe_schema(knowledge: KnowledgeStore) -> dict[str, Any]:
    return {"schema": knowledge.schema()}


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


def run_query(turn: TurnContext, sql: str, grant: Grant) -> dict[str, Any]:
    settings = turn.settings
    attempt = SqlAttempt(sql=sql)
    turn.attempts.append(attempt)
    with turn.tracer.span("tool.run_query", attempt=len(turn.attempts)):
        turn.progress("dry_run", {})
        while True:
            verdict = _guard(turn, sql, grant)
            if isinstance(verdict, sql_guard.Blocked):
                attempt.error = verdict.reason
                if verdict.refusal:
                    raise TurnStop(verdict.reason)  # type: ignore[arg-type]
                return {"error": verdict.llm_text}
            attempt.final_sql = verdict.sql

            with turn.tracer.span("bq.dry_run") as span:
                try:
                    estimate = turn.warehouse.dry_run(verdict.sql, verdict.params)
                except WarehouseError as error:
                    span.set("error", str(error))
                    if verdict.route == "threshold_view" and _view_missing(error):
                        # ADR 0005: an expired view in the sandbox. Use the HAVING fallback from now on.
                        turn.threshold.view = None
                        turn.tracer.log("threshold_view.unavailable")
                        continue
                    attempt.error = str(error)
                    return {"error": f"The query failed in the dry run. Fix it. Detail: {error}"}
                span.set("bytes", estimate)
                if estimate > settings.budget.query_bytes:
                    span.set("over_limit", True)
                    attempt.error = "budget"
                    raise TurnStop("budget", "query bytes")
            break

        turn.progress("query", {})
        query_id = turn.next_query_id()
        with turn.tracer.span("bq.query", sql=verdict.sql) as span:
            try:
                result = turn.warehouse.run(
                    verdict.sql,
                    verdict.params,
                    max_bytes=settings.budget.query_bytes,
                    timeout_s=settings.timeout.bq_job_s,
                    job_id=f"dca-{turn.trace_id}-{query_id}-{len(turn.attempts)}",
                )
            except WarehouseError as error:
                attempt.error = str(error)
                span.set("error", str(error))
                return {"error": f"The query failed. Fix it. Detail: {error}"}
            rows = [[jsonable(value) for value in row] for row in result.rows]
            span.set("bytes", result.bytes_processed)
            span.set("rows", len(rows))
            span.set("columns", result.columns)
        if not rows and verdict.route != "scoped":
            raise TurnStop("threshold")

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


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
