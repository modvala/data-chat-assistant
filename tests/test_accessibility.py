"""Accessible plain output and the progress states (cli.md DS4, C3, Accessibility)."""

import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from typer.testing import CliRunner

from dca.app.turn_api import TurnAPI
from dca.cli.main import detect_mode, make_app, make_console
from dca.cli.render import Mode, Renderer
from dca.config import Settings
from dca.core.answer import (
    Answer,
    Confirmation,
    ConfirmationItem,
    Heading,
    Kpi,
    Notice,
    Provenance,
    Refusal,
    Table,
    Column,
    Text,
    TraceRow,
    TraceView,
)
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call

SQL = "SELECT brand, SUM(sale_price) AS revenue FROM scoped_order_items GROUP BY brand"
ANSI = "\x1b["


class Stream(io.StringIO):
    def __init__(self, tty: bool, encoding: str = "utf-8") -> None:
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    def isatty(self) -> bool:
        return self._tty

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._encoding


def sample_answers() -> list[Answer]:
    provenance = Provenance(brand_scope=["Allegra K"], sql=["SELECT 1"], corrections=1, trace_id="7f3a9c00aa")
    table = Table(
        query_id="q1",
        columns=[Column(name="brand"), Column(name="revenue", type="money")],
        rows=[["Calvin Klein", 1200.5], ["Allegra K", None]],
        total_rows=30,
        truncated=True,
    )
    return [
        Answer(
            kind="answer",
            blocks=[Heading(text="Revenue"), Kpi(label="Revenue", value="$1.2K", delta="+9.3%"), Text(markdown="- one\n- two"), table],
            provenance=provenance,
        ),
        Answer(kind="notice", blocks=[Refusal(reason="pii", title="I can't show personal data", body="b", suggestion="s")]),
        Answer(kind="notice", blocks=[Notice(level="error", title="The data service did not answer", trace_id="7f3a9c00")]),
        Answer(
            kind="confirmation",
            blocks=[
                Confirmation(
                    action="delete",
                    description="These reports mention Customer 4521:",
                    items=[ConfirmationItem(id=str(n), title=f"Report {n}", date="2026-10-01") for n in range(5)],
                    count=7,
                    reply_text="delete 7",
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    undo_window_h=24,
                )
            ],
        ),
        Answer(
            kind="answer",
            blocks=[
                TraceView(
                    trace_id="7f3a9c00",
                    started=datetime.now(UTC),
                    duration_ms=4200,
                    outcome="answered",
                    rows=[TraceRow(label="llm m", status="ok", detail="1 → 2 tokens"), TraceRow(label="bigquery", status="error")],
                )
            ],
        ),
    ]


def render_on_terminal(mode: Mode) -> str:
    buffer = io.StringIO()
    console = make_console(mode, file=buffer, force_terminal=True, width=90)
    renderer = Renderer(console, mode, header_max_brands=3)
    for result in sample_answers():
        renderer.answer(result)
    return buffer.getvalue()


def test_ac_core_1_no_color_writes_no_ansi_codes_also_on_a_terminal() -> None:
    assert ANSI in render_on_terminal(Mode(color=True)), "the check must see codes when color is on"
    output = render_on_terminal(Mode(color=False))
    assert ANSI not in output
    assert "⊘ I can't show personal data" in output and "✗ The data service did not answer" in output


def test_ac_core_1_ascii_mode_uses_ascii_symbols_only_on_a_terminal() -> None:
    output = render_on_terminal(Mode(color=False, ascii=True))
    assert output.isascii(), sorted({char for char in output if not char.isascii()})
    assert "[no] I can't show personal data" in output and "[!!] Delete 7 Saved Reports?" in output


@pytest.mark.parametrize("flags", [["--plain"], ["--no-color"], []])
def test_ac_core_1_plain_no_color_and_pipe_output_has_no_ansi_and_tsv_tables(
    make_api: Callable[..., TurnAPI],
    settings: Settings,
    warehouse: FakeWarehouse,
    monkeypatch: pytest.MonkeyPatch,
    flags: list[str],
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    warehouse.on("sale_price", columns=["brand", "revenue"], rows=[["Calvin Klein", 1200.5]])
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "table", "query_id": "q1"}))
    app = make_app(api_factory=lambda _s: make_api(llm), settings_factory=lambda: settings)

    output = CliRunner().invoke(app, ["--executive", "mgr_ana", *flags], input="Revenue?\n/exit\n").output

    assert ANSI not in output
    assert "brand\trevenue\nCalvin Klein\t$1,200" in output


def test_ac_core_1_ascii_flag_gives_ascii_output_in_the_cli(
    make_api: Callable[..., TurnAPI], settings: Settings, warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", columns=["brand", "revenue"], rows=[["Calvin Klein", 1200.5]])
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "table", "query_id": "q1"}))
    app = make_app(api_factory=lambda _s: make_api(llm), settings_factory=lambda: settings)

    output = CliRunner().invoke(app, ["--executive", "mgr_ana", "--ascii"], input="Revenue?\n/help\n/exit\n").output

    assert output.isascii(), sorted({char for char in output if not char.isascii()})
    assert "* Data Chat Assistant" in output and "you > " in output and "| trace " in output


def test_ac_core_1_progress_states_print_as_static_lines_in_a_pipe(
    make_api: Callable[..., TurnAPI], settings: Settings, warehouse: FakeWarehouse
) -> None:
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "table", "query_id": "q1"}))
    app = make_app(api_factory=lambda _s: make_api(llm), settings_factory=lambda: settings)

    output = CliRunner().invoke(app, ["--executive", "mgr_ana", "--no-animation"], input="Revenue?\n/exit\n").output

    lines = [line.removeprefix("you › ") for line in output.splitlines()]
    states = [line for line in lines if line.startswith("· ")]
    assert states == [
        "· Reading the question",
        "· Writing SQL",
        "· Checking the query",
        "· Running the query",
        "· Writing the answer",
    ]


def test_ac_r5_1_turn_api_sends_the_progress_states_in_order(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    warehouse.on("= 1", dry_error="No matching signature")
    llm = ScriptedLLM(
        call("run_query", sql=SQL.replace("GROUP BY", "WHERE status = 1 GROUP BY")),
        call("run_query", sql=SQL),
        answer({"type": "table", "query_id": "q1"}),
    )
    api = make_api(llm)
    events: list[tuple[str, dict[str, Any]]] = []

    api.send_message(api.start_session("mgr_ana").session_id, "Revenue?", lambda e, d: events.append((e, d)))

    assert events == [
        ("thinking", {}),
        ("sql", {}),
        ("dry_run", {}),
        ("sql", {}),
        ("correction", {"attempt": 2, "of": 3}),
        ("dry_run", {}),
        ("query", {}),
        ("writing", {}),
    ]


def test_ac_core_1_status_texts_follow_c3() -> None:
    renderer = Renderer(make_console(Mode(color=False)), Mode(color=False, ascii=True), 3)
    assert renderer.status_text("correction", {"attempt": 2, "of": 3}) == "Fixing the query | attempt 2 of 3"
    assert renderer.status_text("retry", {"seconds": 4}) == "Service is busy, trying again in 4 s"
    assert renderer.status_text("fallback", {}) == "Using the backup model"


@pytest.mark.parametrize(
    ("tty", "encoding", "flags", "env", "expected"),
    [
        (True, "utf-8", {}, {}, Mode(color=True, plain=False, ascii=False, animation=True)),
        (False, "utf-8", {}, {}, Mode(color=False, plain=True, ascii=False, animation=False)),
        (True, "utf-8", {}, {"NO_COLOR": "1"}, Mode(color=False, plain=False, ascii=False, animation=False)),
        (True, "utf-8", {"no_color": True}, {}, Mode(color=False, plain=False, ascii=False, animation=True)),
        (True, "utf-8", {"no_animation": True}, {}, Mode(color=True, plain=False, ascii=False, animation=False)),
        (True, "utf-8", {"ascii_": True}, {}, Mode(color=True, plain=False, ascii=True, animation=True)),
        (True, "latin-1", {}, {}, Mode(color=True, plain=False, ascii=True, animation=True)),
        (True, "utf-8", {"plain": True}, {}, Mode(color=False, plain=True, ascii=False, animation=False)),
    ],
    ids=["tty", "pipe", "NO_COLOR", "--no-color", "--no-animation", "--ascii", "latin-1", "--plain"],
)
def test_ac_core_1_mode_detection(
    monkeypatch: pytest.MonkeyPatch, tty: bool, encoding: str, flags: dict, env: dict, expected: Mode
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    options = {"no_color": False, "plain": False, "ascii_": False, "no_animation": False, **flags}
    assert detect_mode(**options, stream=Stream(tty, encoding)) == expected
