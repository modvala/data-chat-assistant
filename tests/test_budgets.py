"""Turn budgets and Ctrl+C cancel (AC-R5.3, HLD 15.4, 15.5)."""

import re
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dca.app.turn_api import TurnAPI
from dca.cli import main as cli_main
from dca.config import Settings
from dca.core.answer import Answer, Notice, Refusal
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call, hang

SQL = "SELECT SUM(sale_price) AS revenue FROM scoped_order_items"
SQL_2 = "SELECT COUNT(*) AS orders FROM scoped_orders"


def turn_span(settings: Settings) -> dict:
    return [r for r in read_jsonl(Path(settings.paths.trace_file)) if r.get("name") == "turn"][-1]["attributes"]


def ask(api: TurnAPI) -> Answer:
    return api.send_message(api.start_session("mgr_ana").session_id, "Revenue and orders?")


def assert_budget_refusal(result: Answer, words: str) -> None:
    refusal = result.blocks[0]
    assert isinstance(refusal, Refusal) and refusal.reason == "budget", result
    assert words in refusal.body
    shown = refusal.title + refusal.body + (refusal.suggestion or "")
    assert not re.search(r"\d", shown), "a refusal shows no internal values"
    assert not any(word in shown for word in ("llm_", "bytes", "token", "limit")), shown


@pytest.mark.parametrize(
    ("override", "script", "words", "limit"),
    [
        ({"llm_calls": 2}, [call("run_query", sql=SQL), call("run_query", sql=SQL_2), answer()], "more steps", "llm_calls"),
        ({"llm_tokens": 200}, [call("run_query", sql=SQL), call("run_query", sql=SQL_2), answer()], "more text", "llm_tokens"),
        ({"turn_bytes": 1_500_000}, [call("run_query", sql=SQL), call("run_query", sql=SQL_2), answer()], "read more data", "turn_bytes"),
        ({"query_bytes": 500_000}, [call("run_query", sql=SQL), answer()], "too much data", "query_bytes"),
    ],
    ids=["llm calls", "llm tokens", "bytes for each turn", "bytes for each query"],
)
def test_ac_r5_3_each_budget_stops_the_turn_with_a_refusal_budget(
    make_api: Callable[..., TurnAPI],
    make_settings: Callable[..., Settings],
    override: dict,
    script: list,
    words: str,
    limit: str,
) -> None:
    settings = make_settings(budget=override)
    result = ask(make_api(ScriptedLLM(*script), settings_=settings))

    assert_budget_refusal(result, words)
    span = turn_span(settings)
    assert span["turn.outcome"] == "refused" and span["budget.limit"] == limit


def test_ac_r5_3_llm_call_limit_stops_before_the_extra_call(
    make_api: Callable[..., TurnAPI], make_settings: Callable[..., Settings]
) -> None:
    settings = make_settings(budget={"llm_calls": 2})
    llm = ScriptedLLM(*[call("run_query", sql=SQL) for _ in range(5)])

    ask(make_api(llm, settings_=settings))

    assert len(llm.classifier_calls) + len(llm.requests) == 2


def test_ac_r5_3_wall_time_stops_the_turn(make_api: Callable[..., TurnAPI], make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(budget={"wall_time_s": 0.3}, timeout={"llm_call_s": 30})

    result = ask(make_api(ScriptedLLM(hang()), settings_=settings))

    assert_budget_refusal(result, "took longer")
    assert turn_span(settings)["budget.limit"] == "wall_time"


def test_ac_r5_3_corrections_limit_is_a_budget_stop_in_the_trace(
    make_api: Callable[..., TurnAPI], make_settings: Callable[..., Settings], warehouse: FakeWarehouse
) -> None:
    settings = make_settings(budget={"corrections": 1})
    warehouse.on("= 1", dry_error="No matching signature")
    bad = SQL + " WHERE status = 1"

    result = ask(make_api(ScriptedLLM(call("run_query", sql=bad), call("run_query", sql=bad)), settings_=settings))

    assert isinstance(result.blocks[0], Notice) and result.blocks[0].level == "error"
    span = turn_span(settings)
    assert span["turn.outcome"] == "failed" and span["budget.limit"] == "corrections"


def test_ac_r5_3_cancel_stops_the_running_query(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("sale_price", block=True)
    api = make_api(ScriptedLLM(call("run_query", sql=SQL), answer({"type": "text", "markdown": "late"})))
    session = api.start_session("mgr_ana").session_id
    results: list[Answer] = []
    worker = threading.Thread(target=lambda: results.append(api.send_message(session, "Revenue?")))
    worker.start()
    assert warehouse.job_started.wait(timeout=10)

    api.cancel(session)
    worker.join(timeout=10)

    assert results and results[0].blocks[0].title == "Cancelled"  # type: ignore[union-attr]
    assert warehouse.cancels == [warehouse.queries[0].job_id]
    assert turn_span(settings)["turn.outcome"] == "cancelled"
    assert api.send_message(session, "And now?").kind == "answer"


def test_ac_r5_3_cancel_stops_a_waiting_llm_call(make_api: Callable[..., TurnAPI], settings: Settings) -> None:
    llm = ScriptedLLM(hang())
    api = make_api(llm, settings_=settings)
    session = api.start_session("mgr_ana").session_id
    results: list[Answer] = []
    worker = threading.Thread(target=lambda: results.append(api.send_message(session, "Revenue?")))
    worker.start()
    for _ in range(100):
        if llm.requests:
            break
        threading.Event().wait(0.05)

    api.cancel(session)
    worker.join(timeout=10)

    assert results and results[0].blocks[0].title == "Cancelled"  # type: ignore[union-attr]


def test_ac_r5_3_cli_ctrl_c_during_a_turn_shows_cancelled_and_goes_back_to_the_prompt(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    warehouse.on("sale_price", block=True, times=1)
    api = make_api(ScriptedLLM(call("run_query", sql=SQL), answer({"type": "text", "markdown": "Second."})))
    real_wait = cli_main._wait
    pressed = []

    def wait(done: threading.Event) -> None:
        if not pressed and warehouse.job_started.is_set():
            pressed.append(True)
            raise KeyboardInterrupt
        real_wait(done)

    monkeypatch.setattr(cli_main, "_wait", wait)
    app = cli_main.make_app(api_factory=lambda _s: api, settings_factory=lambda: settings)

    output = CliRunner().invoke(app, ["--executive", "mgr_ana"], input="Revenue?\nAnd now?\n/exit\n").output

    assert pressed
    first, rest = output.split("Cancelled", 1)
    assert "you › " in rest and "Second." in rest
