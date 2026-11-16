"""The Turn API (HLD 5): the only entry for the CLI (P20).

Each Turn loads the session state at the start and saves it at the end (P21).
"""

import asyncio
import contextvars
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlglot

from dca.config import Settings
from dca.core import context, drafting, input_guard, messages, reports
from dca.core.answer import Answer, Bullets, Heading, Notice, Provenance, Refusal, SqlView, Text
from dca.core.ports import (
    ConfigStore,
    Grant,
    KnowledgeStore,
    LLMClient,
    ReportStore,
    Role,
    SessionStore,
    Tracer,
    Warehouse,
)
from dca.core.demographic import THRESHOLD_VIEW
from dca.core.state import QueryHandle, SessionState, TurnRecord
from dca.core.turn import DateRange, ThresholdState, TurnContext, TurnStop

ProgressCallback = Callable[[str, dict[str, Any]], None]


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
                )
                progress("thinking", {})
                decision = self._input_guard(text)
                if decision.blocked:
                    answer = self._refusal(turn, TurnStop("not_analysis", decision.reason))
                    outcome = "refused"
                elif decision.intent == "schema_question":
                    answer, outcome = self._schema_answer(turn), "answered"
                else:
                    turn.intent = decision.intent
                    turn.dates = self._date_range()
                    answer, outcome = self._agent_turn(turn, text)
            except Exception as error:  # noqa: BLE001 - the Turn error handler (P15)
                self.tracer.log("turn.error", error=type(error).__name__)
                answer = Answer(
                    kind="notice", blocks=[messages.error_notice(trace_id)], provenance=Provenance(trace_id=trace_id)
                )
                outcome = "failed"
            span.set("turn.outcome", outcome)
        self._record(state, text, answer, outcome, turn)
        return answer

    def cancel(self, session_id: str) -> None:
        """Ctrl+C. The full cancel comes with the Turn budgets (#22)."""

    def command(self, session_id: str, name: str, args: str = "") -> Answer:
        state = self._load(session_id)
        with self.tracer.span("command", command=name):
            trace_id = self.tracer.current_trace_id()
            handler = {
                "scope": self._cmd_scope,
                "sql": self._cmd_sql,
                "save": self._cmd_save,
                "list": self._cmd_list,
            }.get(name)
            if handler is None:
                blocks: list = [Notice(level="info", title="Unknown command", body="Type /help to see the commands.")]
                return Answer(kind="notice", blocks=blocks, provenance=Provenance(trace_id=trace_id))
            answer = handler(state, args)
            answer.provenance.trace_id = trace_id
            return answer

    # --- Turn parts

    def _input_guard(self, text: str) -> input_guard.InputDecision:
        with self.tracer.span("guard.input") as span:
            reason = input_guard.check_rules(text, self.settings.limits.input_max_chars)
            if reason is not None:
                decision = input_guard.InputDecision("other", reason)
            else:
                try:
                    intent, tokens = input_guard.classify(self.llm, text, model=self.settings.fallback_model)
                    span.set("tokens", tokens)
                    decision = input_guard.InputDecision(intent, "intent" if intent == "other" else "")
                except Exception as error:  # noqa: BLE001 - the classifier is only the first filter
                    span.set("error", type(error).__name__)
                    decision = input_guard.InputDecision("analysis", "classifier_unavailable")
            span.set("intent", decision.intent)
            span.set("decision", "blocked" if decision.blocked else "allowed")
            span.set("reason", decision.reason)
        return decision

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
        model = self.settings.model
        try:
            # A copied context: the ADK run must not leave its span as the current span.
            final = contextvars.copy_context().run(
                asyncio.run, self.agent_loop.run(turn, instruction=instruction, message=text, model=model)
            )
        except TurnStop as stop:
            return self._refusal(turn, stop), "refused"
        answer = drafting.answer_from_draft(final, turn, model=model)
        return answer, "refused" if any(isinstance(block, Refusal) for block in answer.blocks) else "answered"

    def _refusal(self, turn: TurnContext, stop: TurnStop) -> Answer:
        self.tracer.log("turn.refusal", reason=stop.reason)
        return Answer(
            kind="notice",
            blocks=[messages.refusal(stop.reason)],
            provenance=drafting.provenance(turn, model=self.settings.model),
        )

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
            state.last_attempts = turn.attempts
        state.turns.append(
            TurnRecord(
                trace_id=answer.provenance.trace_id, message=text, answer=answer, outcome=outcome, query_ids=query_ids
            )
        )
        self.sessions.save(state)

    def _load(self, session_id: str) -> SessionState:
        state = self.sessions.load(session_id)
        if state is None:
            raise UnknownSession(session_id)
        return state

    # --- Commands (no LLM)

    def _cmd_sql(self, state: SessionState, _args: str) -> Answer:
        """The final SQL of the last Answer, after the Brand scope rewrite (cli.md C14). No LLM."""
        last = next((record for record in reversed(state.turns) if record.query_ids), None)
        if last is None:
            notice = Notice(level="info", title="The last Answer ran no SQL", body="Ask a question about the data first.")
            return Answer(kind="notice", blocks=[notice])
        handles = {handle.query_id: handle for handle in state.handles}
        blocks: list = []
        for query_id in last.query_ids:
            handle = handles[query_id]
            pretty = sqlglot.transpile(handle.sql, read="bigquery", write="bigquery", pretty=True)[0]
            blocks.append(SqlView(sql=pretty, bytes_scanned=handle.bytes_scanned, row_count=handle.row_count))
        return Answer(kind="answer", blocks=blocks)

    def _cmd_save(self, state: SessionState, args: str) -> Answer:
        report = reports.save(
            state, owner_id=state.executive_id, title=args, reports=self.reports, tracer=self.tracer, now=self.clock()
        )
        return reports.saved_notice(report)

    def _cmd_list(self, state: SessionState, _args: str) -> Answer:
        return reports.list_answer(self.reports.find(state.executive_id))

    def _cmd_scope(self, state: SessionState, _args: str) -> Answer:
        entry = self.config.access(state.executive_id)
        if entry is None or entry.brands is None:
            blocks: list = [Text(source="code", markdown="Your Brand scope: all brands.")]
        else:
            blocks = [Text(source="code", markdown="Your Brand scope:"), Bullets(source="code", items=list(entry.brands))]
        return Answer(kind="answer", blocks=blocks)
