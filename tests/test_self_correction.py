"""SQL self-correction and the empty-result diagnostic (AC-R5.1, HLD 15.1, cli.md P-CORRECT)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from dca.app.turn_api import TurnAPI
from dca.cli.main import make_app
from dca.cli.render import THEME, Mode, Renderer
from dca.config import Settings
from dca.core.answer import Notice, Refusal, SqlView
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call

# The SQL guard passes it. BigQuery fails it in the dry run: a STRING compared with an INT64.
BAD_SQL = "SELECT SUM(sale_price) AS revenue FROM scoped_order_items WHERE status = 1"
TYPE_ERROR = "No matching signature for operator = for argument types: STRING, INT64"
GOOD_SQL = "SELECT SUM(sale_price) AS revenue FROM scoped_order_items WHERE status = 'Complete'"


def spans(settings: Settings, name: str) -> list[dict]:
    return [r for r in read_jsonl(Path(settings.paths.trace_file)) if r["type"] == "span" and r["name"] == name]


def test_ac_r5_1_llm_fixes_the_query_on_the_second_attempt(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, capsys: pytest.CaptureFixture[str]
) -> None:
    warehouse.on("= 1", dry_error=TYPE_ERROR)
    llm = ScriptedLLM(call("run_query", sql=BAD_SQL), call("run_query", sql=GOOD_SQL), answer({"type": "table", "query_id": "q1"}))
    api = make_api(llm)
    session = api.start_session("mgr_ana")
    events: list[tuple[str, dict[str, Any]]] = []

    result = api.send_message(session.session_id, "Revenue of complete orders?", lambda e, d: events.append((e, d)))

    assert result.kind == "answer" and result.provenance.corrections == 1
    assert ("correction", {"attempt": 2, "of": 3}) in events
    Renderer(Console(theme=THEME), Mode(plain=True), 3).provenance(result.provenance)
    assert "1 correction" in capsys.readouterr().out


def test_ac_r5_1_llm_that_never_fixes_the_query_stops_after_2_corrections(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("= 1", dry_error=TYPE_ERROR)
    llm = ScriptedLLM(*[call("run_query", sql=BAD_SQL) for _ in range(4)], answer({"type": "text", "markdown": "x"}))
    api = make_api(llm)
    session = api.start_session("mgr_ana")
    events: list[tuple[str, dict[str, Any]]] = []

    result = api.send_message(session.session_id, "Revenue?", lambda e, d: events.append((e, d)))

    notice = result.blocks[0]
    assert isinstance(notice, Notice) and notice.level == "error" and notice.trace_id == result.provenance.trace_id
    assert "session continues" in notice.body
    assert len(warehouse.dry_runs) == 3 and warehouse.queries == []
    assert [d for e, d in events if e == "correction"] == [{"attempt": 2, "of": 3}, {"attempt": 3, "of": 3}]
    assert [s["attributes"]["attempt"] for s in spans(settings, "tool.run_query")] == [1, 2, 3]
    turn = spans(settings, "turn")[-1]
    assert turn["attributes"]["turn.outcome"] == "failed"


def test_ac_r5_1_cli_does_not_stop_after_the_last_failed_correction(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("= 1", dry_error=TYPE_ERROR)
    llm = ScriptedLLM(*[call("run_query", sql=BAD_SQL) for _ in range(3)], answer({"type": "text", "markdown": "Fine."}))
    api = make_api(llm)
    app = make_app(api_factory=lambda _s: api, settings_factory=lambda: settings)

    output = CliRunner().invoke(app, ["--executive", "mgr_ana"], input="Revenue?\nAnd orders?\n/exit\n").output

    assert "I could not make a working query" in output
    assert "Fine." in output


def test_ac_r5_1_unknown_column_is_caught_by_the_guard_before_the_dry_run(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    llm = ScriptedLLM(
        call("run_query", sql=GOOD_SQL.replace("sale_price", "sale_prise")),
        call("run_query", sql=GOOD_SQL),
        answer({"type": "table", "query_id": "q1"}),
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "Revenue?")

    assert result.provenance.corrections == 1 and len(warehouse.dry_runs) == 1


def test_ac_r5_1_sql_all_shows_each_attempt_with_its_error(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("= 1", dry_error=TYPE_ERROR)
    llm = ScriptedLLM(
        call("run_query", sql="DELETE FROM scoped_orders WHERE TRUE"),
        call("run_query", sql=BAD_SQL),
        call("run_query", sql=GOOD_SQL),
        answer({"type": "table", "query_id": "q1"}),
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")
    api.send_message(session.session_id, "Revenue?")

    result = api.command(session.session_id, "sql", "all")

    views = [block for block in result.blocks if isinstance(block, SqlView)]
    assert [view.error for view in views] == ["not_read_only", TYPE_ERROR, ""]
    assert "DELETE" in views[0].sql and "= 1" in views[1].sql and "UNNEST(@brands)" in views[2].sql
    assert api.send_message(session.session_id, "x").kind  # the session continues


def test_ac_r5_1_empty_result_runs_one_diagnostic_and_suggests_the_close_value(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("SUM", columns=["revenue"], rows=[])
    warehouse.on("COUNT", columns=["state", "n"], rows=[["California", 812], ["Texas", 640]])
    llm = ScriptedLLM(
        call(
            "run_query",
            sql="SELECT SUM(i.sale_price) AS revenue FROM scoped_order_items AS i "
            "JOIN scoped_customers AS c ON c.id = i.user_id WHERE c.state = 'Califronia'",
        ),
        answer({"type": "text", "markdown": "This must not show."}),
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "Revenue from Califronia?")

    notice = result.blocks[0]
    assert isinstance(notice, Notice) and notice.level == "info"
    assert notice.title == 'No orders from "Califronia"' and notice.body == "Did you mean California?"
    diagnostics = [run for run in warehouse.runs if run.job_id.startswith("dca-diag-")]
    assert len(diagnostics) == 1 and "GROUP BY" in diagnostics[0].sql and "UNNEST(@brands)" in diagnostics[0].sql
    assert len(llm.requests) == 1, "the LLM wrote no Answer for an empty result"
    assert spans(settings, "bq.query")[-1]["attributes"]["rows"] == 0


def test_ac_r5_1_empty_result_on_a_normal_column_lists_real_values(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("SUM", columns=["revenue"], rows=[])
    warehouse.on("COUNT", columns=["status", "n"], rows=[["Complete", 9], ["Shipped", 5], ["Returned", 2]])
    llm = ScriptedLLM(call("run_query", sql=GOOD_SQL.replace("Complete", "Delivered")))
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "Revenue of delivered orders?")

    notice = result.blocks[0]
    assert isinstance(notice, Notice) and notice.title == 'No orders with status "Delivered"'
    assert notice.body == "Some values in your data: Complete, Shipped, Returned. Ask again with one of them."


def test_ac_r2_3_empty_demographic_result_with_a_real_value_is_a_threshold_refusal(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("AVG", columns=["age", "spend"], rows=[])
    warehouse.on("COUNT\\(DISTINCT", columns=["city", "n"], rows=[["Boston", 40]])
    llm = ScriptedLLM(
        call(
            "run_query",
            sql="SELECT c.age, AVG(i.sale_price) AS spend FROM scoped_customers AS c "
            "JOIN scoped_order_items AS i ON c.id = i.user_id WHERE c.city = 'Boston' GROUP BY c.age",
        )
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "Average spend by age in Boston?")

    assert isinstance(result.blocks[0], Refusal) and result.blocks[0].reason == "threshold"


def test_ac_r5_2_library_error_logs_go_to_the_trace_file_not_to_the_terminal(
    make_api: Callable[..., TurnAPI], settings: Settings
) -> None:
    import logging

    from dca.adapters.otel_tracer import JsonlLogHandler

    make_api(ScriptedLLM())
    assert any(isinstance(handler, JsonlLogHandler) for handler in logging.getLogger().handlers)
    try:
        raise RuntimeError("inside ADK")
    except RuntimeError:
        logging.getLogger("google_adk.test").exception("Node execution failed with exception")

    logs = [r for r in read_jsonl(Path(settings.paths.trace_file)) if r.get("event") == "library.log"]
    assert logs[-1]["logger"] == "google_adk.test" and logs[-1]["error"] == "RuntimeError"
    assert "Traceback" not in Path(settings.paths.trace_file).read_text(encoding="utf-8")
