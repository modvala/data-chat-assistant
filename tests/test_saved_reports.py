"""Saved Reports: /save, "save this report" and /list (HLD 7, 10.5)."""

import re
from collections.abc import Callable
from pathlib import Path

from dca.adapters.sqlite_reports import SQLiteReportStore
from dca.app.turn_api import TurnAPI
from dca.config import Settings
from dca.core.answer import Notice, Table
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call

TOP_SQL = "SELECT user_id, SUM(sale_price) AS spend FROM scoped_order_items GROUP BY user_id ORDER BY spend DESC"


def top_customers_llm(*more: dict) -> ScriptedLLM:
    return ScriptedLLM(
        call("run_query", sql=TOP_SQL),
        answer(
            {"type": "heading", "text": "Top Customers by spend"},
            {"type": "text", "markdown": "Customer 999 is not in the list. The top Customer is Customer 4521."},
            {"type": "table", "query_id": "q1"},
        ),
        *more,
    )


def store(settings: Settings) -> SQLiteReportStore:
    return SQLiteReportStore(Path(settings.paths.reports_db))


def test_ac_r3_2_save_command_with_and_without_a_title(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("spend", columns=["user_id", "spend"], rows=[[4521, 1890.0], [77, 1500.0]])
    api = make_api(top_customers_llm())
    session = api.start_session("mgr_ana")
    api.send_message(session.session_id, "Who are the top Customers?")

    first = api.command(session.session_id, "save", "")
    second = api.command(session.session_id, "save", "My top list")

    assert isinstance(first.blocks[0], Notice) and first.blocks[0].title == 'Saved "Top Customers by spend"'
    saved = store(settings).find("mgr_ana")
    assert [report.title for report in saved] == ["Top Customers by spend", "My top list"]
    assert all(report.owner_id == "mgr_ana" and report.created_session_id == session.session_id for report in saved)
    assert saved[0].sql and "UNNEST(@brands)" in saved[0].sql[0]
    assert "Top Customers by spend" in saved[0].body


def test_ac_r3_2_saved_report_records_customer_ids_from_the_rows_not_from_the_llm_text(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("spend", columns=["user_id", "spend"], rows=[[4521, 1890.0], [77, 1500.0]])
    api = make_api(top_customers_llm())
    session = api.start_session("mgr_ana")
    api.send_message(session.session_id, "Who are the top Customers?")

    api.command(session.session_id, "save", "")

    assert store(settings).find("mgr_ana")[0].customer_ids == ["4521", "77"]


def test_ac_core_1_save_this_report_in_natural_language_uses_the_save_report_tool(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("spend", columns=["user_id", "spend"], rows=[[4521, 1890.0]])
    llm = top_customers_llm(
        call("save_report", title="Top Customers, November"),
        answer({"type": "text", "markdown": "I saved the report."}),
    )
    api = make_api(llm)
    session = api.start_session("mgr_ana")
    api.send_message(session.session_id, "Who are the top Customers?")

    api.send_message(session.session_id, "Save this report")

    saved = store(settings).find("mgr_ana")
    assert [(report.title, report.customer_ids) for report in saved] == [("Top Customers, November", ["4521"])]
    spans = [r for r in read_jsonl(Path(settings.paths.trace_file)) if r["type"] == "span" and r["name"] == "report.save"]
    assert spans and spans[-1]["attributes"]["customers"] == 1


def test_ac_r3_2_list_shows_only_the_own_saved_reports(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    api = make_api(top_customers_llm(*top_customers_llm().steps))
    ana = api.start_session("mgr_ana")
    ben = api.start_session("mgr_ben")
    api.send_message(ana.session_id, "Who are the top Customers?")
    api.command(ana.session_id, "save", "Ana report")
    api.send_message(ben.session_id, "Who are the top Customers?")
    api.command(ben.session_id, "save", "Ben report")

    ana_list = api.command(ana.session_id, "list")
    ben_list = api.command(ben.session_id, "list")

    def titles(result: object) -> list[str]:
        table = next(block for block in result.blocks if isinstance(block, Table))  # type: ignore[attr-defined]
        return [row[0] for row in table.rows]

    assert titles(ana_list) == ["Ana report"]
    assert titles(ben_list) == ["Ben report"]
    table = next(block for block in ana_list.blocks if isinstance(block, Table))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", table.rows[0][1])


def test_ac_r3_2_save_with_no_answer_and_list_with_no_reports(make_api: Callable[..., TurnAPI]) -> None:
    api = make_api(ScriptedLLM())
    session = api.start_session("mgr_ana")

    saved = api.command(session.session_id, "save", "")
    listed = api.command(session.session_id, "list")

    assert saved.blocks[0].title == "There is no Answer to save"  # type: ignore[union-attr]
    assert listed.blocks[0].title == "You have no Saved Reports"  # type: ignore[union-attr]
