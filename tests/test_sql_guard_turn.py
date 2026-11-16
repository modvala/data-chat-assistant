"""The SQL guard in a full Turn (spec #10, seam 1): refusals, typed reasons and spans."""

from collections.abc import Callable
from pathlib import Path

from dca.app.turn_api import TurnAPI
from dca.config import Settings
from dca.core.answer import Answer, Refusal
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call, tool_results

OK_SQL = "SELECT SUM(sale_price) AS revenue FROM scoped_order_items"


def refusal_of(result: Answer) -> Refusal:
    assert result.kind == "notice", result
    block = result.blocks[0]
    assert isinstance(block, Refusal), block
    return block


def spans(settings: Settings, name: str) -> list[dict]:
    records = read_jsonl(Path(settings.paths.trace_file))
    return [r for r in records if r["type"] == "span" and r["name"] == name]


def ask(api: TurnAPI, text: str = "Question", executive: str = "mgr_ana") -> Answer:
    session = api.start_session(executive)
    return api.send_message(session.session_id, text)


def test_ac_r2_1_pii_query_gives_a_refusal_with_no_query_and_no_retry(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    llm = ScriptedLLM(
        call("run_query", sql="SELECT CONCAT(first_name, ' ', last_name) AS who FROM scoped_customers"),
        answer({"type": "text", "markdown": "This must not run."}),
    )

    result = ask(make_api(llm), "Show the names of my Customers")

    refusal = refusal_of(result)
    assert refusal.reason == "pii"
    assert warehouse.dry_runs == [] and warehouse.queries == []
    assert len(llm.requests) == 1, "the LLM got a second call after a PII block"
    guard = spans(settings, "guard.sql")[-1]["attributes"]
    assert guard["decision"] == "blocked" and guard["reason"] == "pii"


def test_ac_r2_2_brand_outside_the_scope_gives_a_refusal_scope(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    llm = ScriptedLLM(call("run_query", sql=OK_SQL + " WHERE brand = 'Nike'"))

    result = ask(make_api(llm), "What is the revenue of Nike?")

    assert refusal_of(result).reason == "scope"
    assert warehouse.queries == []


def test_ac_r2_1_refusal_does_not_name_the_rule_or_the_word(make_api: Callable[..., TurnAPI]) -> None:
    pii = ask(make_api(ScriptedLLM(call("run_query", sql="SELECT first_name FROM scoped_customers"))))
    scope = ask(make_api(ScriptedLLM(call("run_query", sql=OK_SQL + " WHERE brand = 'Nike'"))))

    for result, words in ((pii, ["first_name", "pii", "column", "rule"]), (scope, ["Nike", "literal", "rule", "filter"])):
        refusal = refusal_of(result)
        shown = " ".join([refusal.title, refusal.body, refusal.suggestion or ""]).lower()
        assert all(word.lower() not in shown for word in words), shown


def test_ac_r2_1_technical_block_goes_to_the_llm_and_not_to_the_executive(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    seen: list[dict] = []

    def final(request: object) -> dict:
        seen.extend(tool_results(request))  # type: ignore[arg-type]
        return answer({"type": "text", "markdown": "Revenue is shown."}, {"type": "table", "query_id": "q1"})

    llm = ScriptedLLM(
        call("run_query", sql="SELECT SUM(sale_price) AS revenue FROM `bigquery-public-data.thelook_ecommerce.order_items`"),
        call("run_query", sql=OK_SQL),
        final,
    )

    result = ask(make_api(llm), "What is the revenue?")

    assert result.kind == "answer"
    assert "with no dataset name" in seen[0]["error"]
    shown = result.model_dump_json()
    assert "raw_table" not in shown and "dataset name" not in shown
    assert len(warehouse.queries) == 1


def test_ac_r2_1_guard_caps_the_limit_of_the_final_sql(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse
) -> None:
    llm = ScriptedLLM(call("run_query", sql="SELECT user_id FROM scoped_order_items LIMIT 1000"))

    ask(make_api(llm))

    assert warehouse.queries[0].sql.endswith("LIMIT 50")


def test_ac_r5_3_dry_run_over_the_query_bytes_limit_gives_a_refusal_budget(
    make_api: Callable[..., TurnAPI], make_settings: Callable[..., Settings], warehouse: FakeWarehouse
) -> None:
    settings = make_settings(budget={"query_bytes": 5_000})
    warehouse.on("sale_price", bytes=6_000)
    llm = ScriptedLLM(call("run_query", sql=OK_SQL))

    result = ask(make_api(llm, settings_=settings))

    assert refusal_of(result).reason == "budget"
    assert len(warehouse.dry_runs) == 1 and warehouse.queries == []
    dry_run = spans(settings, "bq.dry_run")[-1]["attributes"]
    assert dry_run["bytes"] == 6_000 and dry_run["over_limit"] is True
