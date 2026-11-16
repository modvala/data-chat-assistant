"""The Turn API with fakes behind the ports (spec #10, seam 1)."""

import re
import time
from collections.abc import Callable
from pathlib import Path

from dca.app.turn_api import TurnAPI, UnknownExecutive
from dca.config import Settings
from dca.core.answer import Bullets, Heading, Table, Text
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call, hang

REVENUE_SQL = "SELECT brand, SUM(sale_price) AS revenue FROM scoped_order_items GROUP BY brand"


def revenue_llm(sql: str = REVENUE_SQL) -> ScriptedLLM:
    return ScriptedLLM(
        call("run_query", sql=sql),
        answer(
            {"type": "heading", "text": "Revenue by brand"},
            {"type": "text", "markdown": "Calvin Klein has the most revenue."},
            {"type": "table", "query_id": "q1"},
        ),
    )


def test_ac_core_1_manager_question_gives_an_answer_from_the_query_rows(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", columns=["brand", "revenue"], rows=[["Calvin Klein", 1200.5], ["Allegra K", 800.0]])
    api = make_api(revenue_llm())
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "What is the revenue by brand?")

    assert result.kind == "answer"
    assert isinstance(result.blocks[0], Heading)
    table = next(block for block in result.blocks if isinstance(block, Table))
    assert table.rows == [["Calvin Klein", 1200.5], ["Allegra K", 800.0]]
    assert result.provenance.brand_scope == ["Allegra K", "Calvin Klein"]
    assert result.provenance.trace_id
    assert len(result.provenance.sql) == 1


def test_ac_r2_2_manager_query_binds_the_brands_of_the_grant(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    llm = revenue_llm(REVENUE_SQL.replace("GROUP BY", "WHERE brand IN ('Calvin Klein') GROUP BY"))
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    api.send_message(session.session_id, "Revenue of Calvin Klein?")

    assert len(warehouse.queries) == 1
    query = warehouse.queries[0]
    assert query.params == {"brands": ("Allegra K", "Calvin Klein")}
    assert not re.search(r"(?<!_dca_)scoped_order_items", query.sql)
    assert "UNNEST(@brands)" in query.sql


def test_ac_r2_2_ceo_query_binds_all_brands(make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse) -> None:
    api = make_api(revenue_llm())
    session = api.start_session("ceo")

    result = api.send_message(session.session_id, "What is the revenue by brand?")

    assert warehouse.queries[0].params == {"brands": tuple(warehouse.brands)}
    assert result.provenance.all_brands


def test_ac_core_1_table_values_come_only_from_query_rows(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", columns=["brand", "revenue"], rows=[["Calvin Klein", 10.0]])
    llm = ScriptedLLM(
        call("run_query", sql=REVENUE_SQL),
        answer({"type": "table", "query_id": "q1", "rows": [["Calvin Klein", 999999]], "columns": ["x"]}),
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "Revenue?")

    table = next(block for block in result.blocks if isinstance(block, Table))
    assert table.rows == [["Calvin Klein", 10.0]]
    assert [column.name for column in table.columns] == ["brand", "revenue"]


def test_ac_r2_1_blocked_sql_does_not_reach_the_warehouse(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    llm = ScriptedLLM(
        call("run_query", sql="DELETE FROM scoped_orders WHERE TRUE"),
        answer({"type": "text", "markdown": "I could not run it."}),
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")

    api.send_message(session.session_id, "Remove the orders")

    assert warehouse.queries == []
    assert warehouse.dry_runs == []
    tool_reply = [part for _, request in llm.requests[1:] for content in request.contents for part in content.parts]
    assert any(part.function_response and "error" in part.function_response.response for part in tool_reply)


def test_ac_core_1_unknown_executive_lists_the_valid_ids(make_api: Callable[..., TurnAPI]) -> None:
    api = make_api(ScriptedLLM())
    try:
        api.start_session("nobody")
    except UnknownExecutive as error:
        assert error.valid_ids == ["ceo", "mgr_ana", "mgr_ben"]
    else:
        raise AssertionError("no error for an unknown Executive")


def test_ac_core_1_scope_command_lists_the_brands(make_api: Callable[..., TurnAPI]) -> None:
    api = make_api(ScriptedLLM())
    manager = api.start_session("mgr_ben")
    ceo = api.start_session("ceo")

    manager_answer = api.command(manager.session_id, "scope")
    ceo_answer = api.command(ceo.session_id, "scope")

    bullets = next(block for block in manager_answer.blocks if isinstance(block, Bullets))
    assert bullets.items == ["Levi's", "Carhartt", "Columbia", "Quiksilver", "Volcom"]
    assert isinstance(ceo_answer.blocks[0], Text) and "all brands" in ceo_answer.blocks[0].markdown


def test_ac_core_1_turn_error_gives_a_notice_and_the_session_continues(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", raise_error=RuntimeError("bug"), times=1)
    api = make_api(revenue_llm())
    session = api.start_session("mgr_ana")

    failed = api.send_message(session.session_id, "Revenue?")

    assert failed.kind == "notice"
    assert failed.blocks[0].type == "notice" and failed.blocks[0].trace_id
    assert api.send_message(session.session_id, "Revenue?").kind == "answer"


def test_ac_r7_1_one_trace_for_the_turn_with_adk_and_our_spans(
    make_api: Callable[..., TurnAPI], settings: Settings
) -> None:
    api = make_api(revenue_llm())
    session = api.start_session("mgr_ana")

    result = api.send_message(session.session_id, "Revenue?")

    spans = [record for record in read_jsonl(Path(settings.paths.trace_file)) if record["type"] == "span"]
    assert {span["trace_id"] for span in spans} == {result.provenance.trace_id}
    names = {span["name"] for span in spans}
    assert {"turn", "guard.sql", "bq.dry_run", "bq.query", "llm.generate", "guard.output"} <= names
    assert any(name.startswith("invoke_agent") for name in names)
    assert any(name.startswith("execute_tool") for name in names)
    by_id = {span["span_id"]: span for span in spans}
    roots = [span for span in spans if span["parent_id"] is None]
    assert [root["name"] for root in roots] == ["turn"]
    assert all(span["parent_id"] in by_id for span in spans if span["parent_id"])
    turn = roots[0]
    assert turn["attributes"]["turn.outcome"] == "answered"


def test_ac_r5_2_llm_call_that_hangs_stops_after_its_timeout(
    make_api: Callable[..., TurnAPI], make_settings: Callable[..., Settings]
) -> None:
    settings = make_settings(timeout={"llm_call_s": 0.1})
    # 3 attempts on the main model and 3 on the fallback model.
    api = make_api(ScriptedLLM(*[hang() for _ in range(6)]), settings_=settings)
    session = api.start_session("mgr_ana")

    started = time.monotonic()
    result = api.send_message(session.session_id, "Revenue?")

    assert time.monotonic() - started < 5
    assert result.kind == "notice"
    assert result.blocks[0].type == "notice" and result.blocks[0].trace_id
