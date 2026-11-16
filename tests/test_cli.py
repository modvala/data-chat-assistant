"""The CLI process with Typer CliRunner and the Turn API on fakes (spec #10, seam 3)."""

from collections.abc import Callable

from rich.console import Console
from typer.testing import CliRunner

from dca.app.turn_api import SessionInfo, TurnAPI
from dca.cli.main import make_app
from dca.cli.render import THEME, Mode, Renderer
from dca.config import Settings
from dca.core.answer import Answer, Heading, Provenance, Text
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
    assert commands == ["/help", "/scope", "/sql", "/save [title]", "/list", "/exit"]


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
