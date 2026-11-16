"""Test seams behind the ports: a scripted LLM and a fake Warehouse (spec #10, Testing Decisions)."""

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types
from pydantic import ConfigDict

from dca.core.ports import LLMResult, LLMTransientError, QueryResult, WarehouseError, WarehouseTransientError

ALL_BRANDS = ["Allegra K", "Calvin Klein", "Carhartt", "Columbia", "Levi's", "Nike", "Quiksilver", "Volcom"]

Step = dict[str, Any] | Callable[[LlmRequest], dict[str, Any]]


# --- Script steps


def call(name: str, **args: Any) -> dict[str, Any]:
    """The LLM calls a tool."""
    return {"kind": "call", "name": name, "args": args}


def answer(*blocks: dict[str, Any]) -> dict[str, Any]:
    """The LLM gives the final answer as JSON blocks."""
    return {"kind": "text", "text": json.dumps({"blocks": list(blocks)})}


def text(value: str) -> dict[str, Any]:
    return {"kind": "text", "text": value}


def fail(status: int = 429, retry_after: float | None = None) -> dict[str, Any]:
    return {"kind": "fail", "status": status, "retry_after": retry_after}


def hang() -> dict[str, Any]:
    """The LLM call never returns."""
    return {"kind": "hang"}


def tool_results(request: LlmRequest) -> list[dict[str, Any]]:
    """The function responses that the model got so far in this request."""
    results = []
    for content in request.contents or []:
        for part in content.parts or []:
            if part.function_response is not None:
                results.append(dict(part.function_response.response or {}))
    return results


class ScriptedLLM:
    """One fake for the `LLMClient` port (the classifier) and, through `adk_model`, the Agent loop."""

    def __init__(self, *steps: Step, intent: str = "analysis", tokens: tuple[int, int] = (100, 20)) -> None:
        self.steps: list[Step] = list(steps)
        self.intent = intent
        self.tokens = tokens
        self.requests: list[tuple[str, LlmRequest]] = []
        self.classifier_calls: list[tuple[str, str]] = []
        self.always_fail: int | None = None
        self.fail_models: set[str] = set()  # these models always fail with a 503
        self.classifier_failures = 0  # the first n classifier calls fail with a 429

    # LLMClient port
    def generate(self, prompt: str, *, model: str, system: str = "", json_schema: dict | None = None) -> LLMResult:
        self.classifier_calls.append((model, prompt))
        if self.always_fail is not None:
            raise LLMTransientError(self.always_fail)
        if self.classifier_failures:
            self.classifier_failures -= 1
            raise LLMTransientError(429)
        return LLMResult(text=json.dumps({"intent": self.intent}), tokens_in=50, tokens_out=5)

    # ADK model factory
    def adk_model(self, model: str) -> BaseLlm:
        return ScriptedAdkModel(model=model, owner=self)

    def next_step(self, model: str, request: LlmRequest) -> dict[str, Any]:
        self.requests.append((model, request))
        if self.always_fail is not None:
            return fail(self.always_fail)
        if model in self.fail_models:
            return fail(503)
        if not self.steps:
            return answer({"type": "text", "markdown": "Script ended."})
        step = self.steps.pop(0)
        return step(request) if callable(step) else step


class ScriptedAdkModel(BaseLlm):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    owner: Any

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        step = self.owner.next_step(self.model, llm_request)
        if step["kind"] == "hang":
            await asyncio.sleep(3600)
        if step["kind"] == "fail":
            raise LLMTransientError(step["status"], step["retry_after"])
        if step["kind"] == "call":
            part = types.Part(function_call=types.FunctionCall(name=step["name"], args=step["args"]))
        else:
            part = types.Part(text=step["text"])
        tokens_in, tokens_out = self.owner.tokens
        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=tokens_in, candidates_token_count=tokens_out, total_token_count=tokens_in + tokens_out
            ),
        )


@dataclass
class Rule:
    pattern: re.Pattern[str]
    columns: list[str]
    rows: list[list[Any]]
    bytes: int = 1_000_000
    error: str | None = None
    dry_error: str | None = None
    raise_error: BaseException | None = None
    transient: bool = False  # a timeout of the job: WarehouseTransientError with the job ID
    times: int | None = None


@dataclass
class Call:
    sql: str
    params: dict[str, tuple[str, ...]]
    job_id: str = ""
    max_bytes: int = 0


@dataclass
class FakeWarehouse:
    """Returns fixed rows for each SQL shape. Records the final SQL and the bound `@brands`."""

    brands: list[str] = field(default_factory=lambda: list(ALL_BRANDS))
    rules: list[Rule] = field(default_factory=list)
    runs: list[Call] = field(default_factory=list)
    dry_runs: list[Call] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)
    date_range: tuple[str, str] = ("2019-01-06", "2026-10-15")

    def on(
        self,
        pattern: str,
        columns: Sequence[str] = ("n",),
        rows: Sequence[Sequence[Any]] = ((1,),),
        **options: Any,
    ) -> "FakeWarehouse":
        self.rules.append(Rule(re.compile(pattern, re.IGNORECASE | re.DOTALL), list(columns), [list(r) for r in rows], **options))
        return self

    def _rule(self, sql: str) -> Rule:
        for rule in self.rules:
            if rule.pattern.search(sql) and (rule.times is None or rule.times > 0):
                return rule
        return Rule(re.compile(""), ["n"], [[1]])

    @property
    def queries(self) -> list[Call]:
        """The runs of LLM queries, without the brand list query of our code."""
        return [run for run in self.runs if not run.job_id.startswith(("dca-brands-", "dca-dates-"))]

    def dry_run(self, sql: str, params: dict[str, Sequence[str]]) -> int:
        self.dry_runs.append(Call(sql, {k: tuple(v) for k, v in params.items()}))
        rule = self._rule(sql)
        if rule.dry_error:
            raise WarehouseError(rule.dry_error)
        return rule.bytes

    def run(
        self, sql: str, params: dict[str, Sequence[str]], *, max_bytes: int, timeout_s: float, job_id: str
    ) -> QueryResult:
        self.runs.append(Call(sql, {k: tuple(v) for k, v in params.items()}, job_id, max_bytes))
        if job_id.startswith("dca-brands-"):
            return QueryResult(job_id, ["brand"], [[b] for b in self.brands], 1000)
        if job_id.startswith("dca-dates-"):
            return QueryResult(job_id, ["min", "max"], [list(self.date_range)], 1000)
        rule = self._rule(sql)
        if rule.times is not None:
            rule.times -= 1
        if rule.raise_error is not None:
            raise rule.raise_error
        if rule.transient:
            raise WarehouseTransientError("timeout", job_id=job_id)
        if rule.error:
            raise WarehouseError(rule.error)
        return QueryResult(job_id, list(rule.columns), [list(r) for r in rule.rows], rule.bytes)

    def cancel(self, job_id: str) -> None:
        self.cancels.append(job_id)
