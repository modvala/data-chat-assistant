"""The Turn API (HLD 5): the only entry for the CLI (P20).

Each Turn loads the session state at the start and saves it at the end (P21).
"""

import asyncio
import contextvars
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dca.config import Settings
from dca.core import context, drafting, messages
from dca.core.answer import Answer, Bullets, Notice, Provenance, Text
from dca.core.ports import ConfigStore, Grant, KnowledgeStore, Role, SessionStore, Tracer, Warehouse
from dca.core.state import QueryHandle, SessionState, TurnRecord
from dca.core.turn import TurnContext, TurnStop

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
        agent_loop: Any,
    ) -> None:
        self.settings = settings
        self.config = config_store
        self.sessions = session_store
        self.warehouse = warehouse
        self.tracer = tracer
        self.knowledge = knowledge
        self.agent_loop = agent_loop
        self.access = AccessResolver(config_store, warehouse, settings)

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
                )
                progress("thinking", {})
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
            handler = {"scope": self._cmd_scope}.get(name)
            if handler is None:
                blocks: list = [Notice(level="info", title="Unknown command", body="Type /help to see the commands.")]
                return Answer(kind="notice", blocks=blocks, provenance=Provenance(trace_id=trace_id))
            answer = handler(state, args)
            answer.provenance.trace_id = trace_id
            return answer

    # --- Turn parts

    def _agent_turn(self, turn: TurnContext, text: str) -> tuple[Answer, str]:
        instruction = context.instruction(turn, self.knowledge.schema())
        model = self.settings.model
        try:
            # A copied context: the ADK run must not leave its span as the current span.
            final = contextvars.copy_context().run(
                asyncio.run, self.agent_loop.run(turn, instruction=instruction, message=text, model=model)
            )
        except TurnStop as stop:
            return self._refusal(turn, stop), "refused"
        return drafting.answer_from_draft(final, turn, model=model), "answered"

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
                        columns=query.columns,
                        row_count=len(query.rows),
                        bytes_scanned=query.bytes_scanned,
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

    def _cmd_scope(self, state: SessionState, _args: str) -> Answer:
        entry = self.config.access(state.executive_id)
        if entry is None or entry.brands is None:
            blocks: list = [Text(source="code", markdown="Your Brand scope: all brands.")]
        else:
            blocks = [Text(source="code", markdown="Your Brand scope:"), Bullets(source="code", items=list(entry.brands))]
        return Answer(kind="answer", blocks=blocks)
