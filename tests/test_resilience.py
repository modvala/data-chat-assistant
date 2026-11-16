"""LLM and BigQuery failures: backoff, the backup model, the Turn error handler and chaos mode (AC-R5.2)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dca.adapters import chaos
from dca.adapters.local_stores import InMemorySessionStore, JsonConfigStore, SchemaKnowledgeStore
from dca.adapters.otel_tracer import JsonlTracer
from dca.adapters.sqlite_reports import SQLiteReportStore
from dca.agent.adk_loop import AdkAgentLoop
from dca.app.turn_api import TurnAPI
from dca.cli.main import make_app
from dca.cli.render import THEME, Mode, Renderer
from dca.config import Settings
from dca.core import drafting
from dca.core.answer import Answer, Notice
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call, fail, tool_results

SQL = "SELECT SUM(sale_price) AS revenue FROM scoped_order_items"
FORBIDDEN = ("503", "429", "Gemini", "Google", "BigQuery", "Traceback", "status", "Error")


def spans(settings: Settings, name: str) -> list[dict]:
    return [r for r in read_jsonl(Path(settings.paths.trace_file)) if r["type"] == "span" and r["name"] == name]


def ask(api: TurnAPI, events: list | None = None) -> Answer:
    session = api.start_session("mgr_ana")
    return api.send_message(session.session_id, "Revenue?", (lambda e, d: events.append((e, d))) if events is not None else None)


def assert_friendly_error(result: Answer) -> None:
    notice = result.blocks[0]
    assert isinstance(notice, Notice) and notice.level == "error"
    assert notice.title == "The data service did not answer"
    assert "Your session continues." in notice.body and notice.trace_id == result.provenance.trace_id
    shown = notice.title + notice.body
    assert not any(word in shown for word in FORBIDDEN), shown


def test_ac_r5_2_llm_429_then_success_gives_an_answer_after_backoff(
    make_api: Callable[..., TurnAPI], settings: Settings
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    llm = ScriptedLLM(fail(429), answer({"type": "text", "markdown": "Revenue is $10."}))

    result = ask(make_api(llm), events)

    assert result.kind == "answer" and not result.provenance.fallback_used
    retries = [data for event, data in events if event == "retry"]
    assert len(retries) == 1 and retries[0]["seconds"] >= 1
    assert spans(settings, "llm.generate")[-1]["attributes"]["retries"] == 1


def test_ac_r5_2_retry_after_is_used(make_api: Callable[..., TurnAPI], make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(retry={"backoff_min_s": 0.001, "backoff_max_s": 3.0})
    events: list[tuple[str, dict[str, Any]]] = []
    llm = ScriptedLLM(fail(429, retry_after=0.01), answer({"type": "text", "markdown": "Done."}))

    ask(make_api(llm, settings_=settings), events)

    assert [data for event, data in events if event == "retry"] == [{"seconds": 1}]


def test_ac_r5_2_main_model_failure_gives_an_answer_from_the_backup_model(
    make_api: Callable[..., TurnAPI], settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "table", "query_id": "q1"}))
    llm.fail_models = {settings.model}

    result = ask(make_api(llm), events)

    assert result.kind == "answer"
    assert result.provenance.fallback_used and result.provenance.model == settings.fallback_model
    assert ("fallback", {}) in events
    assert [model for model, _ in llm.requests] == [settings.model] * 3 + [settings.fallback_model] * 2
    calls = spans(settings, "llm.generate")
    assert calls[0]["attributes"]["retries"] == 2 and calls[0]["status"] == "ERROR"
    assert calls[-1]["attributes"]["fallback_used"] is True
    Renderer(Console(theme=THEME), Mode(plain=True), 3).provenance(result.provenance)
    assert "backup model" in capsys.readouterr().out


def test_ac_r5_2_all_retries_and_the_backup_model_fail_gives_a_friendly_error(make_api: Callable[..., TurnAPI]) -> None:
    llm = ScriptedLLM()
    llm.always_fail = 503

    result = ask(make_api(llm))

    assert_friendly_error(result)
    assert len(llm.requests) == 6


def test_ac_r5_2_bigquery_timeout_gets_one_retry_and_a_cancel(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", transient=True, times=1)
    warehouse.on("sale_price", columns=["revenue"], rows=[[10.0]])
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "table", "query_id": "q1"}))

    result = ask(make_api(llm))

    assert result.kind == "answer"
    jobs = [run.job_id for run in warehouse.queries]
    assert len(jobs) == 2 and jobs[1] == jobs[0] + "-r1"
    assert warehouse.cancels == [jobs[0]]


def test_ac_r5_2_bigquery_down_after_the_retry_gives_a_friendly_error(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", transient=True)
    llm = ScriptedLLM(call("run_query", sql=SQL))

    result = ask(make_api(llm))

    assert_friendly_error(result)
    assert len(warehouse.queries) == 2 and len(warehouse.cancels) == 2


def test_ac_r5_2_classifier_429_gets_a_retry(make_api: Callable[..., TurnAPI]) -> None:
    llm = ScriptedLLM(intent="other")
    llm.classifier_failures = 1

    result = ask(make_api(llm))

    assert len(llm.classifier_calls) == 2
    assert result.blocks[0].type == "refusal"


def test_ac_r5_2_bug_in_our_code_gives_an_error_notice_and_the_session_continues(
    make_api: Callable[..., TurnAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = ScriptedLLM(answer({"type": "text", "markdown": "One."}), answer({"type": "text", "markdown": "Two."}))
    api = make_api(llm)
    session = api.start_session("mgr_ana")
    real = drafting.answer_from_draft
    monkeypatch.setattr(drafting, "answer_from_draft", lambda *a, **k: 1 / 0)

    failed = api.send_message(session.session_id, "Revenue?")
    monkeypatch.setattr(drafting, "answer_from_draft", real)
    recovered = api.send_message(session.session_id, "Revenue again?")

    assert_friendly_error(failed)
    assert recovered.kind == "answer"


def test_ac_r5_2_cli_prints_the_error_notice_and_goes_back_to_the_prompt(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("sale_price", raise_error=RuntimeError("bug"), times=1)
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "text", "markdown": "Second answer."}))
    app = make_app(api_factory=lambda _s: make_api(llm), settings_factory=lambda: settings)

    result = CliRunner().invoke(app, ["--executive", "mgr_ana"], input="Revenue?\nAnd now?\n/exit\n")

    assert result.exit_code == 0
    first, rest = result.output.split("The data service did not answer", 1)
    assert "you › " in rest and "Second answer." in rest


class AgentPolicy(ScriptedLLM):
    """Always the same plan: run one query, then answer with its table."""

    def next_step(self, model: str, request: Any) -> dict[str, Any]:
        self.requests.append((model, request))
        if any("query_id" in result for result in tool_results(request)):
            return answer({"type": "table", "query_id": "q1"})
        return call("run_query", sql=SQL)


def test_ac_r5_2_chaos_mode_20_turns_give_no_exception(
    settings: Settings, warehouse: FakeWarehouse, tmp_path: Path
) -> None:
    llm = AgentPolicy()
    chaos_llm, model_factory, chaos_warehouse = chaos.wrap(
        "llm_429:0.3,bq_timeout:0.1", 7, llm, llm.adk_model, warehouse
    )
    knowledge = SchemaKnowledgeStore()
    api = TurnAPI(
        settings=settings,
        config_store=JsonConfigStore(Path(settings.paths.executives)),
        session_store=InMemorySessionStore(),
        warehouse=chaos_warehouse,
        tracer=JsonlTracer(Path(settings.paths.trace_file)),
        knowledge=knowledge,
        llm=chaos_llm,
        agent_loop=AdkAgentLoop(model_factory, knowledge),
        report_store=SQLiteReportStore(tmp_path / "chaos.sqlite"),
    )
    session = api.start_session("mgr_ana")

    results = [api.send_message(session.session_id, f"Revenue {n}?") for n in range(20)]

    for result in results:
        assert result.provenance.trace_id
        if result.kind != "answer":
            assert_friendly_error(result)
    assert sum(result.kind == "answer" for result in results) >= 15
    assert any(s["attributes"].get("retries") for s in spans(settings, "llm.generate"))
    assert warehouse.cancels, "chaos made at least one BigQuery timeout"


def test_ac_r5_2_chaos_spec_rejects_an_unknown_fault() -> None:
    with pytest.raises(ValueError, match="Unknown CHAOS fault"):
        chaos.Chaos("llm_42:0.5")
