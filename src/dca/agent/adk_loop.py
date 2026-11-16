"""The framework adapter: Google ADK runs the Agent loop (ADR 0003). It makes no safety decision.

For each Turn it builds a fresh ADK session from the state that the Turn API loaded, so the ADK
session service holds nothing that the next Turn needs (P21). The grant goes into the session
state, and the tool wrappers pass it to the core tools.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, Gemini, LlmRequest, LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import ConfigDict

from dca.core import tools
from dca.core.ports import Grant, KnowledgeStore, LLMTransientError
from dca.core.turn import TurnContext

APP_NAME = "dca"
ModelFactory = Callable[[str], BaseLlm]


def gemini_factory(model: str) -> BaseLlm:
    # One attempt only. Our model wrapper does the backoff, so that the CLI can show it (ADR 0003).
    return Gemini(model=model, retry_options=types.HttpRetryOptions(attempts=1))


class TurnModel(BaseLlm):
    """Wraps the real model: one `llm.generate` span and one progress event for each call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: BaseLlm
    turn: Any
    fallback_used: bool = False

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        turn: TurnContext = self.turn
        turn.progress("writing" if turn.queries else "sql", {})
        timeout_s = turn.settings.timeout.llm_call_s
        # V9: an LLM call stops after its timeout. The HTTP timeout closes the socket, and the
        # asyncio timeout also stops a call that hangs somewhere else.
        if llm_request.config is not None:
            options = llm_request.config.http_options or types.HttpOptions()
            options.timeout = int(timeout_s * 1000)
            llm_request.config.http_options = options
        with turn.tracer.span("llm.generate", model=self.inner.model, fallback_used=self.fallback_used) as span:
            started = time.monotonic()
            tokens_in = tokens_out = 0
            responses = []
            try:
                async with asyncio.timeout(timeout_s):
                    async for response in self.inner.generate_content_async(llm_request, stream):
                        responses.append(response)
            except TimeoutError:
                span.set("error", "timeout")
                raise LLMTransientError(504) from None
            for response in responses:
                usage = response.usage_metadata
                if usage:
                    tokens_in = usage.prompt_token_count or tokens_in
                    tokens_out = usage.candidates_token_count or tokens_out
                yield response
            span.set("tokens_in", tokens_in)
            span.set("tokens_out", tokens_out)
            span.set("latency_ms", round((time.monotonic() - started) * 1000))


def _grant(state: Any) -> Grant:
    data = state["grant"]
    return Grant(executive_id=data["executive_id"], role=data["role"], brands=tuple(data["brands"]))


class AdkAgentLoop:
    def __init__(self, model_factory: ModelFactory, knowledge: KnowledgeStore) -> None:
        self.model_factory = model_factory
        self.knowledge = knowledge

    def _tools(self, turn: TurnContext) -> list[Callable[..., dict]]:
        knowledge = self.knowledge

        def run_query(sql: str, tool_context: ToolContext) -> dict:
            """Run one BigQuery SELECT on the scoped views. Returns a query_id, the columns and the rows."""
            return tools.run_query(turn, sql, _grant(tool_context.state))

        def describe_schema() -> dict:
            """Return the description of the scoped views and their columns."""
            return tools.describe_schema(knowledge)

        def save_report(title: str, tool_context: ToolContext) -> dict:
            """Save the last Answer of this conversation as a Saved Report. Use an empty title for the default."""
            return tools.save_report(turn, title, _grant(tool_context.state))

        def list_reports(tool_context: ToolContext) -> dict:
            """List the Saved Reports of the Executive, with titles and dates."""
            return tools.list_reports(turn, _grant(tool_context.state))

        def plan_delete(
            tool_context: ToolContext,
            customer_ids: list[str] | None = None,
            this_conversation: bool = False,
            customer_name: str = "",
        ) -> dict:
            """Plan a delete of Saved Reports. It deletes nothing: the Executive must confirm.

            Give customer_ids for "reports mentioning Customer X", or this_conversation=true for
            "reports we made in this conversation". If the Executive names a Customer by name, give customer_name.
            """
            return tools.plan_delete(
                turn,
                _grant(tool_context.state),
                customer_ids=[str(cid) for cid in customer_ids or []],
                this_conversation=this_conversation,
                customer_name=customer_name,
            )

        return [run_query, describe_schema, save_report, list_reports, plan_delete]

    async def run(
        self, turn: TurnContext, *, instruction: str, message: str, model: str, fallback_used: bool = False
    ) -> str:
        agent = LlmAgent(
            name="analyst",
            model=TurnModel(
                model=model, inner=self.model_factory(model), turn=turn, fallback_used=fallback_used
            ),
            instruction=lambda _context: instruction,
            tools=self._tools(turn),
        )
        sessions = InMemorySessionService()
        grant = turn.grant
        session = await sessions.create_session(
            app_name=APP_NAME,
            user_id=grant.executive_id,
            session_id=uuid.uuid4().hex,
            state={"grant": {"executive_id": grant.executive_id, "role": grant.role, "brands": list(grant.brands)}},
        )
        runner = Runner(app_name=APP_NAME, agent=agent, session_service=sessions)
        content = types.Content(role="user", parts=[types.Part(text=message)])
        final = ""
        async for event in runner.run_async(user_id=grant.executive_id, session_id=session.id, new_message=content):
            if event.is_final_response() and event.content and event.content.parts:
                final = "".join(part.text or "" for part in event.content.parts if not part.thought)
        return final
