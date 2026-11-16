"""The Turn API (HLD 5): the only entry for the CLI (P20).

Each Turn loads the session state at the start and saves it at the end (P21).
"""

import asyncio
import contextvars
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import sqlglot

from dca.config import Settings
from dca.core import backoff, budget, confirmation, context, drafting, input_guard, messages, reports, trace_view
from dca.core.budget import TurnBudget
from dca.core.answer import Answer, Bullets, Heading, Notice, Provenance, Refusal, Result, SqlView, Text
from dca.core.ports import (
    AuditEntry,
    ConfigStore,
    Grant,
    KnowledgeStore,
    LLMClient,
    LLMTransientError,
    LLMUnavailable,
    ReportStore,
    Role,
    SessionStore,
    Tracer,
    Warehouse,
)
from dca.core.demographic import THRESHOLD_VIEW
from dca.core.state import QueryHandle, SessionState, TurnRecord
from dca.core.turn import DateRange, ThresholdState, TurnCancelled, TurnContext, TurnFinish, TurnStop

ProgressCallback = Callable[[str, dict[str, Any]], None]
T = TypeVar("T")


def _pretty(sql: str) -> str:
    try:
        return sqlglot.transpile(sql, read="bigquery", write="bigquery", pretty=True)[0]
    except sqlglot.errors.SqlglotError:
        return sql


class _GateDone(Exception):
    """The Confirmation gate handled the message. The Turn ends here."""


class UnknownExecutive(Exception):
    def __init__(self, valid_ids: list[str]) -> None:
        super().__init__("unknown executive")
        self.valid_ids = valid_ids


class UnknownSession(Exception):
    pass


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    executive_id: str
    role: Role
    brands: tuple[str, ...] | None


class AccessResolver:
    """Makes the grant of an Executive. For the CEO, it loads all brands one time and caches them."""

    def __init__(self, config: ConfigStore, warehouse: Warehouse, settings: Settings) -> None:
        self.config = config
        self.warehouse = warehouse
        self.settings = settings
        self._all_brands: tuple[str, ...] | None = None

    def grant(self, executive_id: str) -> Grant:
        entry = self.config.access(executive_id)
        if entry is None:
            raise UnknownExecutive(self.config.executive_ids())
        brands = entry.brands if entry.brands is not None else self.all_brands()
        return Grant(executive_id=entry.executive_id, role=entry.role, brands=brands)

    def all_brands(self) -> tuple[str, ...]:
        if self._all_brands is None:
            dataset = self.settings.warehouse.source_dataset
            result = self.warehouse.run(
                f"SELECT DISTINCT brand FROM `{dataset}.products` WHERE brand IS NOT NULL ORDER BY brand",
                {},
                max_bytes=self.settings.budget.query_bytes,
                timeout_s=self.settings.timeout.bq_job_s,
                job_id=f"dca-brands-{uuid.uuid4().hex}",
            )
            self._all_brands = tuple(str(row[0]) for row in result.rows)
        return self._all_brands


class TurnAPI:
    def __init__(
        self,
        *,
        settings: Settings,
        config_store: ConfigStore,
        session_store: SessionStore,
        warehouse: Warehouse,
        tracer: Tracer,
        knowledge: KnowledgeStore,
        llm: LLMClient,
        agent_loop: Any,
        report_store: ReportStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.config = config_store
        self.sessions = session_store
        self.warehouse = warehouse
        self.tracer = tracer
        self.knowledge = knowledge
        self.llm = llm
        self.agent_loop = agent_loop
        self.reports = report_store
        self.clock = clock
        self._dates: DateRange | None = None
        self._active: dict[str, tuple[TurnContext, asyncio.AbstractEventLoop | None, asyncio.Task | None]] = {}
        self.access = AccessResolver(config_store, warehouse, settings)
        project, dataset = settings.google_cloud_project, settings.warehouse.threshold_dataset
        self.threshold = ThresholdState(f"{project}.{dataset}.{THRESHOLD_VIEW}" if project else None)

    # --- Operations of HLD 5.1

    def start_session(self, executive_id: str) -> SessionInfo:
        entry = self.config.access(executive_id)
        if entry is None:
            raise UnknownExecutive(self.config.executive_ids())
        state = SessionState(session_id=uuid.uuid4().hex, executive_id=executive_id)
        self.sessions.save(state)
        return SessionInfo(state.session_id, executive_id, entry.role, entry.brands)

    def send_message(self, session_id: str, text: str, on_progress: ProgressCallback | None = None) -> Answer:
        state = self._load(session_id)
        progress = on_progress or (lambda _event, _data: None)
        with self.tracer.span(
            "turn",
            session_id=session_id,
            executive_id=state.executive_id,
            persona_version=self.settings.persona_version,
        ) as span:
            trace_id = self.tracer.current_trace_id()
            turn: TurnContext | None = None
            try:
                progress("thinking", {})
                gate_answer, gate_outcome, gate_notices = self._confirmation_gate(state, text, trace_id)
                if gate_answer is not None:
                    answer, outcome = gate_answer, gate_outcome
                    raise _GateDone
                grant = self.access.grant(state.executive_id)
                span.set("role", grant.role)
                turn = TurnContext(
                    grant=grant,
                    session=state,
                    trace_id=trace_id,
                    settings=self.settings,
                    warehouse=self.warehouse,
                    tracer=self.tracer,
                    progress=progress,
                    threshold=self.threshold,
                    reports=self.reports,
                    now=self.clock(),
                    budget=TurnBudget(self.settings.budget),
                )
                self._active[session_id] = (turn, None, None)
                # A reply to a delete preview is not a follow-up: classify it with no earlier questions.
                decision = self._input_guard(text, progress, turn, follow_up=not gate_notices)
                if decision.blocked and gate_notices and decision.reason == "intent":
                    # A reply such as "no, keep them" to a delete preview only cancels it (cli.md P-TURN).
                    answer, outcome = Answer(kind="notice", blocks=[]), "cancelled"
                elif decision.blocked:
                    answer = self._refusal(turn, TurnStop("not_analysis", decision.reason))
                    outcome = "refused"
                elif decision.intent == "schema_question":
                    answer, outcome = self._schema_answer(turn), "answered"
                else:
                    turn.intent = decision.intent
                    turn.dates = self._date_range()
                    answer, outcome = self._agent_turn(turn, text)
                answer.blocks = gate_notices + answer.blocks
            except _GateDone:
                pass
            except TurnCancelled:
                answer = Answer(kind="notice", blocks=[Notice(level="info", title="Cancelled", body="Your session continues.")])
                outcome = "cancelled"
            except Exception as error:  # noqa: BLE001 - the Turn error handler (P15)
                self.tracer.log("turn.error", error=type(error).__name__)
                answer = Answer(
                    kind="notice", blocks=[messages.error_notice(trace_id)], provenance=Provenance(trace_id=trace_id)
                )
                outcome = "failed"
            span.set("turn.outcome", outcome)
            if turn is not None and turn.budget is not None:
                span.set("budget.llm_calls", turn.budget.llm_calls)
                span.set("budget.llm_tokens", turn.budget.llm_tokens)
                span.set("budget.bytes", turn.budget.bytes_scanned)
                cost = self.settings.cost
                span.set(
                    "turn.cost_usd",
                    round(
                        turn.budget.llm_tokens / 1000 * cost.llm_usd_per_1k_tokens
                        + turn.budget.bytes_scanned / 2**40 * cost.bq_usd_per_tib,
                        6,
                    ),
                )
            if turn is not None and turn.stop_limit:
                span.set("budget.limit", turn.stop_limit)
            self._active.pop(session_id, None)
        answer.provenance.trace_id = answer.provenance.trace_id or trace_id
        answer.awaiting_confirmation = state.pending is not None
        self._record(state, text, answer, outcome, turn)
        return answer

    def cancel(self, session_id: str) -> None:
        """Ctrl+C: stops the running Turn of the session and its BigQuery job (HLD 15.5)."""
        active = self._active.get(session_id)
        if active is None:
            return
        turn, loop, task = active
        turn.cancelled = True
        if turn.running_job:
            self.warehouse.cancel(turn.running_job)
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)

    def command(self, session_id: str, name: str, args: str = "") -> Answer:
        state = self._load(session_id)
        with self.tracer.span("command", command=name):
            trace_id = self.tracer.current_trace_id()
            handler = {
                "scope": self._cmd_scope,
                "sql": self._cmd_sql,
                "save": self._cmd_save,
                "list": self._cmd_list,
                "undo": self._cmd_undo,
                "trace": self._cmd_trace,
            }.get(name)
            if handler is None:
                blocks: list = [Notice(level="info", title="Unknown command", body="Type /help to see the commands.")]
                return Answer(kind="notice", blocks=blocks, provenance=Provenance(trace_id=trace_id))
            answer = handler(state, args)
            answer.provenance.trace_id = trace_id
            answer.awaiting_confirmation = state.pending is not None  # A command does not cancel (HLD 6.2).
            return answer

    # --- Turn parts

    def _confirmation_gate(self, state: SessionState, text: str, trace_id: str) -> tuple[Answer | None, str, list]:
        """Reads the message before the Input guard and the LLM (ADR 0002, HLD 10).

        Returns an Answer when the gate handles the message, else the notices to show before the
        normal Turn. Only the exact reply of the owner, in the same session, with the same ID set
        and before the expiry, deletes.
        """
        pending = state.pending
        if pending is None:
            return None, "", []
        now = self.clock()
        with self.tracer.span("confirmation") as span:
            span.set("count", len(pending.report_ids))
            if now >= pending.expires_at:
                state.pending = None
                span.set("state", "expired")
                return None, "", [Notice(level="info", title="The delete request expired. Nothing was deleted.")]
            exact = confirmation.is_exact_reply(text, pending)
            bound = pending.executive_id == state.executive_id and pending.session_id == state.session_id
            if not (exact and bound):
                state.pending = None
                span.set("state", "cancelled")
                return None, "", [Notice(level="info", title="Nothing was deleted.")]
            ids = sorted(report.report_id for report in confirmation.matching(self.reports, state.executive_id, pending))
            if confirmation.ids_hash(ids) != pending.ids_hash:
                answer, state.pending = confirmation.preview(self.reports, pending, now=now, settings=self.settings)
                span.set("state", "changed")
                return answer, "pending" if state.pending else "answered", []
            undo_until = now + timedelta(hours=self.settings.confirmation.undo_window_h)
            batch = self.reports.soft_delete(ids, actor=state.executive_id, undo_until=undo_until, at=now)
            self.reports.audit(AuditEntry(state.executive_id, "delete", batch.batch_id, batch.report_ids, trace_id, now))
            state.pending = None
            span.set("state", "done")
            span.set("batch_id", batch.batch_id)
        result = Result(action="deleted", count=len(ids), undo_until=undo_until)
        return Answer(kind="answer", blocks=[result]), "done", []

    def _input_guard(
        self, text: str, progress: ProgressCallback, turn: TurnContext, *, follow_up: bool = True
    ) -> input_guard.InputDecision:
        with self.tracer.span("guard.input") as span:
            reason = input_guard.check_rules(text, self.settings.limits.input_max_chars)
            if reason is not None:
                decision = input_guard.InputDecision("other", reason)
            else:
                try:
                    if turn.budget:
                        turn.budget.before_llm_call()
                    # Only answered Turns: a refused message does not come back (HLD 9.4).
                    earlier = [r.message for r in turn.session.turns if r.outcome == "answered" and follow_up]
                    earlier = earlier[max(0, len(earlier) - self.settings.limits.classifier_questions) :]
                    intent, tokens = self._classify(text, earlier, progress)
                    span.set("tokens", tokens)
                    if turn.budget:
                        turn.budget.add_tokens(tokens)
                    decision = input_guard.InputDecision(intent, "intent" if intent == "other" else "")
                except Exception as error:  # noqa: BLE001 - the classifier is only the first filter
                    span.set("error", type(error).__name__)
                    decision = input_guard.InputDecision("analysis", "classifier_unavailable")
            span.set("intent", decision.intent)
            span.set("decision", "blocked" if decision.blocked else "allowed")
            span.set("reason", decision.reason)
        return decision

    def _classify(self, text: str, earlier: list[str], progress: ProgressCallback) -> tuple[str, int]:
        """The classifier call with backoff for a 429, a 5xx or a timeout (V8)."""
        return self._llm_retry(
            lambda: input_guard.classify(self.llm, text, model=self.settings.fallback_model, earlier=earlier), progress
        )

    def _llm_retry(self, call: Callable[[], T], progress: ProgressCallback) -> T:
        """A direct LLM call with backoff for a 429, a 5xx or a timeout (V8)."""
        retry = self.settings.retry
        for attempt in range(retry.llm_retries + 1):
            try:
                return call()
            except LLMTransientError as error:
                if attempt == retry.llm_retries:
                    raise
                wait = backoff.delay(attempt + 1, error.retry_after, retry)
                progress("retry", {"seconds": max(1, round(wait))})
                time.sleep(wait)
        raise AssertionError("unreachable")

    def _schema_answer(self, turn: TurnContext) -> Answer:
        """A schema question gets an Answer from the schema description, with no query."""
        blocks: list = [
            Heading(source="code", text="The data you can analyze"),
            Text(
                source="code",
                markdown="You can ask about the sales, orders and Customers of your brands. "
                "Customers show only by ID, with no names or contact data.",
            ),
            Text(source="code", markdown=self.knowledge.schema()),
            Bullets(
                source="code",
                items=[
                    "What was the revenue by month this year?",
                    "Who are the top 10 Customers by total spend?",
                    "Compare the revenue of two brands, and tell me why they differ.",
                    "Create a report for Q1 with insights and action items for Q2.",
                ],
            ),
        ]
        return Answer(kind="answer", blocks=blocks, provenance=drafting.provenance(turn, model=""))

    def _date_range(self) -> DateRange | None:
        """Today and the min and max order date: one cached query each day (HLD 9.3)."""
        today = self.clock().date().isoformat()
        if self._dates is None or self._dates.today != today:
            dataset = self.settings.warehouse.source_dataset
            try:
                result = self.warehouse.run(
                    f"SELECT MIN(DATE(created_at)), MAX(DATE(created_at)) FROM `{dataset}.orders`",
                    {},
                    max_bytes=self.settings.budget.query_bytes,
                    timeout_s=self.settings.timeout.bq_job_s,
                    job_id=f"dca-dates-{uuid.uuid4().hex}",
                )
                low, high = result.rows[0]
                self._dates = DateRange(today, str(low)[:10], str(high)[:10])
            except Exception as error:  # noqa: BLE001 - the Turn can go on without the date range
                self.tracer.log("context.dates_unavailable", error=type(error).__name__)
                return None
        return self._dates

    def _agent_turn(self, turn: TurnContext, text: str) -> tuple[Answer, str]:
        with self.tracer.span("context.assemble") as span:
            instruction, tokens = context.instruction(turn, self.knowledge.schema())
            for part, count in tokens.items():
                span.set(f"tokens.{part}", count)
        # After the main model fails its retries, the Turn runs again with the fallback model.
        # ADK does not change models (ADR 0003).
        for model, fallback_used in ((self.settings.model, False), (self.settings.fallback_model, True)):
            if fallback_used:
                turn.progress("fallback", {})
                self.tracer.log("llm.fallback", model=model)
                turn.queries.clear()
                turn.attempts.clear()
                turn.run = 2  # BigQuery rejects a job ID that it has seen.
            try:
                final = self._run_agent(
                    turn,
                    self.agent_loop.run(
                        turn, instruction=instruction, message=text, model=model, fallback_used=fallback_used
                    ),
                )
                break
            except LLMUnavailable:
                if fallback_used and turn.queries:
                    # Both models are down, but the queries have rows: show them (HLD 15.3).
                    self.tracer.log("turn.error", error="LLMUnavailable", answer_from_results=True)
                    return drafting.results_answer(turn, model=model, fallback_used=True), "failed"
                if fallback_used:
                    raise
            except TurnStop as stop:
                return self._refusal(turn, stop), "refused"
            except TurnFinish as finish:
                turn.stop_limit = finish.stop_limit
                return finish.answer, finish.outcome
        if drafting.is_broken_json(final):
            final = self._repair_json(turn, final)
            if drafting.is_broken_json(final):
                return drafting.results_answer(turn, model=model, fallback_used=fallback_used), "failed"
        answer = drafting.answer_from_draft(final, turn, model=model, fallback_used=fallback_used)
        return answer, "refused" if any(isinstance(block, Refusal) for block in answer.blocks) else "answered"

    def _repair_json(self, turn: TurnContext, text: str) -> str:
        """One call on the fallback model, with structured output and backoff, fixes the syntax of the draft.

        A failure or a used budget keeps the draft. The Answer then shows the query results.
        """
        with self.tracer.span("answer.repair") as span:
            try:
                if turn.budget:
                    turn.budget.before_llm_call()
                result = self._llm_retry(
                    lambda: self.llm.generate(
                        text,
                        model=self.settings.fallback_model,
                        system=drafting.REPAIR_SYSTEM,
                        json_schema=drafting.DRAFT_SCHEMA,
                    ),
                    turn.progress,
                )
                if turn.budget:
                    turn.budget.add_tokens(result.tokens_in + result.tokens_out)
            except Exception as error:  # noqa: BLE001 - the repair is best effort
                span.set("error", type(error).__name__)
                span.set("repaired", False)
                return text
            span.set("repaired", not drafting.is_broken_json(result.text))
            return result.text

    def _run_agent(self, turn: TurnContext, coroutine: Any) -> str:
        """Runs the Agent loop inside the rest of the wall-time budget. Ctrl+C cancels the task."""

        async def main() -> str:
            self._active[turn.session.session_id] = (turn, asyncio.get_running_loop(), asyncio.current_task())
            remaining = turn.budget.remaining_s() if turn.budget else None
            try:
                return await asyncio.wait_for(coroutine, timeout=remaining)
            except TimeoutError:
                raise TurnStop("budget", "wall_time") from None
            except asyncio.CancelledError:
                raise TurnCancelled() from None

        # A copied context: the ADK run must not leave its span as the current span.
        return contextvars.copy_context().run(asyncio.run, main())

    def _refusal(self, turn: TurnContext, stop: TurnStop) -> Answer:
        self.tracer.log("turn.refusal", reason=stop.reason, limit=stop.detail if stop.reason == "budget" else "")
        body = budget.LIMIT_TEXT.get(stop.detail) if stop.reason == "budget" else None
        answer = Answer(
            kind="notice",
            blocks=[messages.refusal(stop.reason, body)],
            provenance=drafting.provenance(turn, model=self.settings.model),
        )
        if stop.reason == "budget":
            turn.stop_limit = stop.detail
        return answer

    def _record(self, state: SessionState, text: str, answer: Answer, outcome: str, turn: TurnContext | None) -> None:
        query_ids = []
        if turn is not None:
            for query in turn.queries.values():
                handle_id = f"{answer.provenance.trace_id[:8]}-{query.query_id}"
                query_ids.append(handle_id)
                state.handles.append(
                    QueryHandle(
                        query_id=handle_id,
                        trace_id=answer.provenance.trace_id,
                        sql=query.sql,
                        llm_sql=query.llm_sql,
                        columns=query.columns,
                        row_count=len(query.rows),
                        bytes_scanned=query.bytes_scanned,
                        customer_ids=query.customer_ids,
                    )
                )
        state.turns.append(
            TurnRecord(
                trace_id=answer.provenance.trace_id,
                message=text,
                answer=answer,
                outcome=outcome,
                query_ids=query_ids,
                attempts=turn.attempts if turn is not None else [],
            )
        )
        self.sessions.save(state)

    def _load(self, session_id: str) -> SessionState:
        state = self.sessions.load(session_id)
        if state is None:
            raise UnknownSession(session_id)
        return state

    # --- Commands (no LLM)

    def _cmd_sql(self, state: SessionState, args: str) -> Answer:
        """The final SQL of the last Answer, after the Brand scope rewrite (cli.md C14). No LLM.

        `/sql all` shows each SQL attempt of the last Turn with SQL, and its error.
        """
        if args.strip() == "all":
            record = next((record for record in reversed(state.turns) if record.attempts), None)
            if record is not None:
                views = [
                    SqlView(sql=_pretty(attempt.final_sql or attempt.sql), error=attempt.error)
                    for attempt in record.attempts
                ]
                return Answer(kind="answer", blocks=views)
        last = next((record for record in reversed(state.turns) if record.query_ids), None)
        if last is None:
            notice = Notice(level="info", title="The last Answer ran no SQL", body="Ask a question about the data first.")
            return Answer(kind="notice", blocks=[notice])
        handles = {handle.query_id: handle for handle in state.handles}
        blocks: list = []
        for query_id in last.query_ids:
            handle = handles[query_id]
            blocks.append(SqlView(sql=_pretty(handle.sql), bytes_scanned=handle.bytes_scanned, row_count=handle.row_count))
        return Answer(kind="answer", blocks=blocks)

    def _cmd_save(self, state: SessionState, args: str) -> Answer:
        report = reports.save(
            state, owner_id=state.executive_id, title=args, reports=self.reports, tracer=self.tracer, now=self.clock()
        )
        return reports.saved_notice(report)

    def _cmd_list(self, state: SessionState, _args: str) -> Answer:
        pending = state.pending
        if pending is not None and self.clock() < pending.expires_at:
            matched = [r for r in self.reports.find(state.executive_id) if r.report_id in set(pending.report_ids)]
            return reports.list_answer(matched, title="These Saved Reports match the pending delete")
        return reports.list_answer(self.reports.find(state.executive_id))

    def _cmd_undo(self, state: SessionState, _args: str) -> Answer:
        """Restores the last delete batch of the Executive in the Undo window (A8, AC-R3.3). No LLM."""
        now = self.clock()
        batch = self.reports.last_batch(state.executive_id)
        with self.tracer.span("undo") as span:
            if batch is None or batch.restored:
                span.set("state", "nothing")
                notice = Notice(level="info", title="There is no delete to undo", body="Nothing was restored.")
                return Answer(kind="notice", blocks=[notice])
            span.set("batch_id", batch.batch_id)
            if now > batch.undo_until:
                span.set("state", "window_ended")
                notice = Notice(level="info", title="The Undo window has ended", body="Nothing was restored.")
                return Answer(kind="notice", blocks=[notice])
            restored = self.reports.restore(batch.batch_id, state.executive_id)
            trace_id = self.tracer.current_trace_id()
            self.reports.audit(AuditEntry(state.executive_id, "undo", batch.batch_id, tuple(restored), trace_id, now))
            span.set("state", "restored")
            span.set("count", len(restored))
        return Answer(kind="answer", blocks=[Result(action="restored", count=len(restored))])

    def _cmd_trace(self, state: SessionState, args: str) -> Answer:
        """The span tree of a Turn, from the trace file (AC-R7.3). No LLM. With no ID: the last Turn."""
        wanted = args.strip() or (state.turns[-1].trace_id if state.turns else "")
        records = self.tracer.read(wanted) if wanted else []
        trace_ids = {record["trace_id"] for record in records if record.get("type") == "span"}
        if len(trace_ids) > 1:
            notice = Notice(level="info", title="More than one trace has this ID", body="Type more characters of the ID.")
            return Answer(kind="notice", blocks=[notice])
        view = trace_view.build(records)
        if view is None:
            notice = Notice(level="info", title="No trace has this ID", body="Copy the ID from the line under an Answer.")
            return Answer(kind="notice", blocks=[notice])
        return Answer(kind="answer", blocks=[view])

    def _cmd_scope(self, state: SessionState, _args: str) -> Answer:
        entry = self.config.access(state.executive_id)
        if entry is None or entry.brands is None:
            blocks: list = [Text(source="code", markdown="Your Brand scope: all brands.")]
        else:
            blocks = [Text(source="code", markdown="Your Brand scope:"), Bullets(source="code", items=list(entry.brands))]
        return Answer(kind="answer", blocks=blocks)
