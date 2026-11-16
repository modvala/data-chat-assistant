"""The demographic router in a full Turn (ADR 0005, HLD 8.7)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from rich.console import Console

from dca.app.turn_api import TurnAPI
from dca.cli.render import THEME, Mode, Renderer
from dca.config import Settings
from dca.core.answer import Answer, Refusal, Table
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call, tool_results

SPEND_BY_AGE = (
    "SELECT c.age, AVG(i.sale_price) AS avg_spend FROM scoped_customers AS c "
    "JOIN scoped_order_items AS i ON c.id = i.user_id WHERE c.city = 'Boston' GROUP BY c.age"
)
VIEW = "proj.dca_views.customer_sales_threshold"


@pytest.fixture
def project_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(google_cloud_project="proj")


def ask(api: TurnAPI, llm_text: str = "Average spend by age group in Boston?") -> Answer:
    session = api.start_session("mgr_ana")
    return api.send_message(session.session_id, llm_text)


def guard_routes(settings: Settings) -> list[str]:
    records = read_jsonl(Path(settings.paths.trace_file))
    return [r["attributes"].get("route", "") for r in records if r["type"] == "span" and r["name"] == "guard.sql"]


def spend_llm() -> ScriptedLLM:
    return ScriptedLLM(
        call("run_query", sql=SPEND_BY_AGE),
        answer({"type": "text", "markdown": "Spend by age."}, {"type": "table", "query_id": "q1"}),
    )


def test_ac_r2_3_demographic_aggregate_runs_on_the_threshold_view(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, project_settings: Settings
) -> None:
    warehouse.on(VIEW, columns=["age", "avg_spend"], rows=[[25, 61.5], [30, 58.0]])

    result = ask(make_api(spend_llm(), settings_=project_settings))

    assert result.kind == "answer"
    query = warehouse.queries[0]
    assert f"`{VIEW}`" in query.sql and "SELECT WITH AGGREGATION_THRESHOLD" in query.sql
    assert query.params == {"brands": ("Allegra K", "Calvin Klein")}
    assert guard_routes(project_settings) == ["threshold_view"]


def test_ac_r2_3_threshold_that_hides_all_groups_gives_a_refusal_threshold(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, project_settings: Settings
) -> None:
    warehouse.on(VIEW, columns=["age", "avg_spend"], rows=[])

    result = ask(make_api(spend_llm(), settings_=project_settings))

    assert result.kind == "notice"
    assert isinstance(result.blocks[0], Refusal) and result.blocks[0].reason == "threshold"


def test_ac_r2_3_expired_threshold_view_switches_to_the_having_fallback(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, project_settings: Settings
) -> None:
    warehouse.on(VIEW, dry_error=f"Not found: Table {VIEW} was not found in location US")
    warehouse.on("HAVING COUNT", columns=["age", "avg_spend"], rows=[[25, 61.5]])
    api = make_api(spend_llm(), settings_=project_settings)

    result = ask(api)

    assert result.kind == "answer"
    assert "HAVING COUNT(DISTINCT" in warehouse.queries[0].sql
    assert guard_routes(project_settings) == ["threshold_view", "having_fallback"]
    assert api.threshold.view is None
    events = [r["event"] for r in read_jsonl(Path(project_settings.paths.trace_file)) if r["type"] == "log"]
    assert "threshold_view.unavailable" in events


def test_ac_r2_3_no_project_uses_the_having_fallback(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("HAVING COUNT", columns=["age", "avg_spend"], rows=[[25, 61.5]])

    ask(make_api(spend_llm()))

    assert guard_routes(settings) == ["having_fallback"]


def test_ac_r2_3_demographic_row_list_gives_a_refusal_pii(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, project_settings: Settings
) -> None:
    llm = ScriptedLLM(call("run_query", sql="SELECT id FROM scoped_customers WHERE age = 25 AND city = 'Boston'"))

    result = ask(make_api(llm, settings_=project_settings), "Show all customers aged 25 from Boston")

    assert isinstance(result.blocks[0], Refusal) and result.blocks[0].reason == "pii"
    assert "total" in (result.blocks[0].suggestion or "")
    assert warehouse.dry_runs == []


def test_ac_r2_3_unsupported_demographic_shape_goes_back_to_the_llm(
    make_api: Callable[..., TurnAPI], project_settings: Settings
) -> None:
    seen: list[dict] = []

    def final(request: object) -> dict:
        seen.extend(tool_results(request))  # type: ignore[arg-type]
        return answer({"type": "text", "markdown": "Done."})

    nested = "SELECT city, n FROM (SELECT city, COUNT(DISTINCT id) AS n FROM scoped_customers GROUP BY city)"
    llm = ScriptedLLM(call("run_query", sql=nested), final)

    result = ask(make_api(llm, settings_=project_settings))

    assert result.kind == "answer"
    assert "one aggregate SELECT" in seen[0]["error"]


def test_ac_r2_3_top_customers_by_spend_shows_customer_ids(
    make_api: Callable[..., TurnAPI],
    warehouse: FakeWarehouse,
    project_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    warehouse.on("spend", columns=["user_id", "spend"], rows=[[4521, 1890.0], [77, 1500.0]])
    llm = ScriptedLLM(
        call(
            "run_query",
            sql="SELECT user_id, SUM(sale_price) AS spend FROM scoped_order_items GROUP BY user_id ORDER BY spend DESC",
        ),
        answer({"type": "table", "query_id": "q1"}),
    )

    result = ask(make_api(llm, settings_=project_settings), "Top customers by total spend?")

    table = next(block for block in result.blocks if isinstance(block, Table))
    assert table.columns[0].type == "customer"
    Renderer(Console(theme=THEME, width=80), Mode(plain=True), header_max_brands=3).answer(result)
    assert "Customer 4521\t$1,890" in capsys.readouterr().out
