"""The Output guard and the block validator (HLD 8.8, cli.md DS3)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from dca.app.turn_api import TurnAPI
from dca.config import Settings
from dca.core import output_guard
from dca.core.answer import Answer, Refusal, Text
from tests.conftest import read_jsonl
from tests.fakes import FakeWarehouse, ScriptedLLM, answer, call

SQL = "SELECT user_id, SUM(sale_price) AS spend FROM scoped_order_items GROUP BY user_id"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("Write to ann.lee+shop@example.co.uk today.", "email"),
        ("Call (617) 555-0199.", "phone"),
        ("Call 617-555-0199.", "phone"),
        ("Call +44 20 7946 0958.", "phone"),
        ("She lives at 123 Main Street.", "street_address"),
        ("Ship to 4 Elm St. please", "street_address"),
        ("The store is at 42.3601, -71.0589.", "coordinates"),
    ],
)
def test_ac_r2_1_output_guard_finds_pii_patterns(value: str, reason: str) -> None:
    assert output_guard.check([Text(markdown=value)]) == reason


@pytest.mark.parametrize(
    "value",
    [
        "Revenue was $1,234,567.89 in 2026-10.",
        "Orders on 2026-10-01 and 2026-10-01T12:00:00+00:00.",
        "Churn is 4.3% ▼ -0.4 pp; 12,480 orders in 2026-Q1.",
        "Levi's 501 Original Jeans sold best. Customer 4521 spent the most.",
        "See trace 7f3a9c, or type /sql.",
        "Average latitude is 42.3601.",
    ],
)
def test_ac_r2_1_output_guard_passes_normal_analysis_text(value: str) -> None:
    assert output_guard.check([Text(markdown=value)]) is None


def ask(api: TurnAPI) -> Answer:
    session = api.start_session("mgr_ana")
    return api.send_message(session.session_id, "Who are my top Customers?")


def output_span(settings: Settings) -> dict:
    records = read_jsonl(Path(settings.paths.trace_file))
    return [r for r in records if r["type"] == "span" and r["name"] == "guard.output"][-1]["attributes"]


@pytest.mark.parametrize(
    "leak",
    ["Contact ann@example.com for details.", "Call 617-555-0199.", "Visit 12 Beacon Street.", "At 42.3601, -71.0589."],
)
def test_ac_r2_1_pii_in_llm_text_becomes_a_refusal_pii(
    make_api: Callable[..., TurnAPI], settings: Settings, leak: str
) -> None:
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "text", "markdown": f"Top Customer. {leak}"}))

    result = ask(make_api(llm))

    assert result.kind == "notice"
    assert isinstance(result.blocks[0], Refusal) and result.blocks[0].reason == "pii"
    assert leak not in result.model_dump_json()
    assert output_span(settings)["decision"] == "blocked"
    turn = [r for r in read_jsonl(Path(settings.paths.trace_file)) if r.get("name") == "turn"][-1]
    assert turn["attributes"]["turn.outcome"] == "refused"


def test_ac_r2_1_table_with_customer_id_and_demographic_column_becomes_a_refusal_pii(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("spend", columns=["user_id", "age", "spend"], rows=[[4521, 34, 1890.0]])
    llm = ScriptedLLM(call("run_query", sql=SQL), answer({"type": "table", "query_id": "q1"}))

    result = ask(make_api(llm))

    assert isinstance(result.blocks[0], Refusal) and result.blocks[0].reason == "pii"
    assert output_span(settings)["reason"] == "id_with_demographics"


def test_ac_r2_1_block_validator_drops_code_only_blocks_from_the_llm(
    make_api: Callable[..., TurnAPI], settings: Settings
) -> None:
    llm = ScriptedLLM(
        answer(
            {"type": "text", "markdown": "Revenue grew."},
            {
                "type": "confirmation",
                "action": "delete",
                "description": "Delete all?",
                "items": [],
                "count": 9,
                "reply_text": "yes",
                "expires_at": "2026-11-16T10:00:00Z",
                "undo_window_h": 24,
            },
            {"type": "refusal", "reason": "pii", "title": "x", "body": "y"},
            {"type": "notice", "level": "info", "title": "Nothing was deleted."},
            {"type": "result", "action": "deleted", "count": 9},
        )
    )

    result = ask(make_api(llm))

    assert [block.type for block in result.blocks] == ["text"]
    assert result.awaiting_confirmation is False
    span = output_span(settings)
    assert span["dropped_blocks"] == ["confirmation", "refusal", "notice", "result"]
    assert span["decision"] == "allowed"


def test_ac_r7_1_no_pii_value_from_the_rows_gets_into_the_trace(
    make_api: Callable[..., TurnAPI], warehouse: FakeWarehouse, settings: Settings
) -> None:
    warehouse.on("spend", columns=["user_id", "spend", "note"], rows=[[4521, 1890.0, "ann@example.com"]])
    llm = ScriptedLLM(
        call("run_query", sql=SQL),
        answer({"type": "text", "markdown": "The top Customer is ann@example.com."}, {"type": "table", "query_id": "q1"}),
    )

    result = ask(make_api(llm))

    assert isinstance(result.blocks[0], Refusal)
    assert "ann@example.com" not in Path(settings.paths.trace_file).read_text(encoding="utf-8")
