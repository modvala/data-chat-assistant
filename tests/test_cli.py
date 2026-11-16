"""The CLI process with Typer CliRunner and the Turn API on fakes (spec #10, seam 3)."""

from collections.abc import Callable

from rich.console import Console
from typer.testing import CliRunner

from dca.app.turn_api import SessionInfo, TurnAPI
from dca.cli.main import make_app
from dca.cli.render import THEME, Mode, Renderer
from dca.config import Settings
from dca.core.answer import Answer, Column, Heading, Provenance, Table, Text
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call

runner = CliRunner()


def run_cli(api: TurnAPI, settings: Settings, *args: str, input: str = "") -> object:
    app = make_app(api_factory=lambda _settings: api, settings_factory=lambda: settings)
    return runner.invoke(app, list(args), input=input)


def test_ac_core_1_header_for_a_manager_with_few_brands(make_api: Callable[..., TurnAPI], settings: Settings) -> None:
    result = run_cli(make_api(ScriptedLLM()), settings, "--executive", "mgr_ana", input="/exit\n")
    assert result.exit_code == 0
    assert "Executive mgr_ana · Manager · Brand scope: Allegra K, Calvin Klein" in result.output


def test_ac_core_1_header_for_a_manager_with_more_than_3_brands(
    make_api: Callable[..., TurnAPI], settings: Settings
) -> None:
    result = run_cli(make_api(ScriptedLLM()), settings, "--executive", "mgr_ben", input="/exit\n")
    assert "Brand scope: 5 brands (/scope to list)" in result.output


def test_ac_core_1_header_for_the_ceo(make_api: Callable[..., TurnAPI], settings: Settings) -> None:
    result = run_cli(make_api(ScriptedLLM()), settings, "--executive", "ceo", input="/exit\n")
    assert "Executive ceo · CEO · Brand scope: all brands" in result.output


def test_ac_core_1_unknown_executive_exits_with_code_2(make_api: Callable[..., TurnAPI], settings: Settings) -> None:
    result = run_cli(make_api(ScriptedLLM()), settings, "--executive", "nobody")
    assert result.exit_code == 2
    assert "Unknown Executive ID" in result.output
    assert "Valid IDs: ceo, mgr_ana, mgr_ben." in result.output
    assert "Data Chat Assistant" not in result.output


def test_ac_core_1_help_lists_only_the_commands_that_work(make_api: Callable[..., TurnAPI], settings: Settings) -> None:
    result = run_cli(make_api(ScriptedLLM()), settings, "--executive", "mgr_ana", input="/help\n/exit\n")
    lines = [line.removeprefix("you › ") for line in result.output.splitlines()]
    commands = [line.split("\t")[0] for line in lines if line.startswith("/")]
    assert commands == ["/help", "/scope", "/sql [all]", "/save [title]", "/list", "/undo", "/trace [id]", "/exit"]


def test_ac_core_1_scope_command_and_ctrl_d(make_api: Callable[..., TurnAPI], settings: Settings) -> None:
    result = run_cli(make_api(ScriptedLLM()), settings, "--executive", "mgr_ben", input="/scope\n")
    assert result.exit_code == 0
    for brand in ["Levi's", "Carhartt", "Columbia", "Quiksilver", "Volcom"]:
        assert f"- {brand}" in result.output or f"• {brand}" in result.output


def test_ac_core_1_question_prints_the_answer_and_the_provenance_line(
    make_api: Callable[..., TurnAPI], settings: Settings, warehouse: FakeWarehouse
) -> None:
    warehouse.on("sale_price", columns=["brand", "revenue"], rows=[["Calvin Klein", 1200.5]])
    llm = ScriptedLLM(
        call("run_query", sql="SELECT brand, SUM(sale_price) AS revenue FROM scoped_order_items GROUP BY brand"),
        answer({"type": "heading", "text": "Revenue by brand"}, {"type": "table", "query_id": "q1"}),
    )
    result = run_cli(make_api(llm), settings, "--executive", "mgr_ana", input="Revenue by brand?\n/exit\n")
    assert "brand\trevenue" in result.output
    assert "Calvin Klein\t$1,200" in result.output
    assert "Scope: Allegra K, Calvin Klein · trace " in result.output
    assert "/sql" in result.output


def test_ac_core_1_answer_panel_on_a_terminal() -> None:
    console = Console(theme=THEME, force_terminal=True, record=True, width=80)
    renderer = Renderer(console, Mode(), header_max_brands=3)
    renderer.header(SessionInfo("s1", "mgr_ana", "manager", ("Allegra K", "Calvin Klein")))
    renderer.answer(
        Answer(
            kind="answer",
            blocks=[Heading(text="Revenue"), Text(markdown="Revenue grew.")],
            provenance=Provenance(brand_scope=["Allegra K", "Calvin Klein"], trace_id="7f3a9c00"),
        )
    )
    output = console.export_text()
    assert "◆ Data Chat Assistant" in output
    assert "╭─ ◆ Revenue" in output
    assert "Scope: Allegra K, Calvin Klein · trace 7f3a9c00" in output


def _wide_answer() -> Answer:
    years = [f"y{year}" for year in range(2019, 2027)]
    columns = [Column(name="brand"), *(Column(name=name, type="number") for name in [*years, "total"])]
    rows = [
        ["Calvin Klein", 1121.5, 3641.2, 8389.7, 11226.4, 15620.9, 22481.3, 32652.8, 55861.1, 150996.12],
        ["Allegra K", 579.96, 1677.3, 3254.8, 4654.1, 7124.5, 9844.2, 14388.6, 25033.4, 66556.21],
    ]
    table = Table(query_id="q1", columns=columns, rows=rows, total_rows=2)
    return Answer(kind="answer", blocks=[Heading(text="Revenue by Brand and Year"), table])


def _render(answer: Answer, width: int) -> str:
    console = Console(theme=THEME, force_terminal=True, record=True, width=width)
    Renderer(console, Mode(), header_max_brands=3).answer(answer)
    return console.export_text()


def test_ac_core_1_wide_table_uses_the_terminal_width_and_shows_full_values() -> None:
    output = _render(_wide_answer(), width=160)
    assert "…" not in output
    assert "Calvin Klein" in output
    assert "150,996.12" in output
    assert 100 < max(len(line) for line in output.splitlines()) < 160


def test_ac_core_1_table_on_a_narrow_terminal_wraps_values_and_does_not_cut_them() -> None:
    output = _render(_wide_answer(), width=100)
    assert "…" not in output
    assert max(len(line) for line in output.splitlines()) <= 100


def test_ac_core_1_text_panel_stays_at_width_max_on_a_wide_terminal() -> None:
    answer = Answer(kind="answer", blocks=[Heading(text="Revenue"), Text(markdown="Revenue grew. " * 20)])
    output = _render(answer, width=160)
    assert max(len(line) for line in output.splitlines()) == 100
