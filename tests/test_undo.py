"""/undo restores the last delete batch in the Undo window (AC-R3.3, HLD 10.3)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from dca.app.turn_api import TurnAPI
from dca.config import Settings
from dca.core.answer import Notice, Result, Table
from tests.conftest import read_jsonl
from tests.fakes import ScriptedLLM
from tests.test_delete_confirmation import DELETE_4521, Clock, add, plan


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def deleted(make_api: Callable[..., TurnAPI], clock: Clock) -> tuple[TurnAPI, str, ScriptedLLM]:
    """mgr_ana deleted 2 of her 3 Saved Reports."""
    llm = plan()
    api = make_api(llm)
    api.clock = clock
    add(api, "mgr_ana", "A", ["4521"])
    add(api, "mgr_ana", "B", ["4521"])
    add(api, "mgr_ana", "Keep", ["77"])
    session = api.start_session("mgr_ana").session_id
    assert api.send_message(session, DELETE_4521).kind == "confirmation"
    assert isinstance(api.send_message(session, "delete 2").blocks[0], Result)
    return api, session, llm


def listed(api: TurnAPI, session: str) -> list[str]:
    answer = api.command(session, "list")
    table = next((block for block in answer.blocks if isinstance(block, Table)), None)
    return [row[0] for row in table.rows] if table else []


def test_ac_r3_3_undo_in_the_window_restores_the_last_batch(
    deleted: tuple[TurnAPI, str, ScriptedLLM], clock: Clock, settings: Settings
) -> None:
    api, session, _ = deleted
    assert listed(api, session) == ["Keep"]
    clock.now += timedelta(hours=23)

    result = api.command(session, "undo")

    assert isinstance(result.blocks[0], Result)
    assert result.blocks[0].action == "restored" and result.blocks[0].count == 2
    assert listed(api, session) == ["A", "B", "Keep"]
    undo = [r for r in read_jsonl(Path(settings.paths.trace_file)) if r.get("name") == "undo"][-1]
    assert undo["attributes"]["state"] == "restored" and undo["attributes"]["count"] == 2


def test_ac_r3_3_undo_after_the_window_restores_nothing(
    deleted: tuple[TurnAPI, str, ScriptedLLM], clock: Clock
) -> None:
    api, session, _ = deleted
    clock.now += timedelta(hours=24, seconds=1)

    result = api.command(session, "undo")

    assert isinstance(result.blocks[0], Notice) and result.blocks[0].title == "The Undo window has ended"
    assert listed(api, session) == ["Keep"]


def test_ac_r3_3_undo_twice_restores_one_time(deleted: tuple[TurnAPI, str, ScriptedLLM]) -> None:
    api, session, _ = deleted
    api.command(session, "undo")

    second = api.command(session, "undo")

    assert second.blocks[0].title == "There is no delete to undo"  # type: ignore[union-attr]


def test_ac_r3_2_another_executive_cannot_undo_the_batch(deleted: tuple[TurnAPI, str, ScriptedLLM]) -> None:
    api, session, _ = deleted
    ben = api.start_session("mgr_ben").session_id

    result = api.command(ben, "undo")

    assert result.blocks[0].title == "There is no delete to undo"  # type: ignore[union-attr]
    batch = api.reports.last_batch("mgr_ana")
    assert batch is not None
    assert api.reports.restore(batch.batch_id, "mgr_ben") == []
    assert listed(api, session) == ["Keep"]


def test_ac_r3_3_each_undo_writes_an_audit_entry(deleted: tuple[TurnAPI, str, ScriptedLLM]) -> None:
    api, session, _ = deleted

    result = api.command(session, "undo")

    entries = list(api.reports.audit_entries("mgr_ana"))
    assert [entry.action for entry in entries] == ["delete", "undo"]
    undo = entries[-1]
    assert undo.batch_id == entries[0].batch_id and set(undo.report_ids) == set(entries[0].report_ids)
    assert undo.trace_id == result.provenance.trace_id and undo.trace_id


def test_ac_r3_3_confirmation_and_undo_work_when_the_llm_is_down(
    make_api: Callable[..., TurnAPI], clock: Clock
) -> None:
    llm = plan()
    api = make_api(llm)
    api.clock = clock
    add(api, "mgr_ana", "A", ["4521"])
    session = api.start_session("mgr_ana").session_id
    assert api.send_message(session, DELETE_4521).kind == "confirmation"
    llm.always_fail = 503

    deleted = api.send_message(session, "yes")
    restored = api.command(session, "undo")

    assert isinstance(deleted.blocks[0], Result) and deleted.blocks[0].action == "deleted"
    assert isinstance(restored.blocks[0], Result) and restored.blocks[0].action == "restored"
    assert listed(api, session) == ["A"]
