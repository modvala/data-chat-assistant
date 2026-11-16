import json
import os
import socket
from collections.abc import Callable
from pathlib import Path

import pytest

from dca.adapters.local_stores import InMemorySessionStore, JsonConfigStore, SchemaKnowledgeStore
from dca.adapters.otel_tracer import JsonlTracer
from dca.agent.adk_loop import AdkAgentLoop
from dca.app.turn_api import TurnAPI
from dca.config import ROOT, Settings
from tests.fakes import FakeWarehouse, ScriptedLLM

EXECUTIVES = ROOT / "executives.json"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", help="Run the tests that need Gemini and BigQuery.")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def offline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline tests use no network, no API key and no GCP project."""
    if "live" in request.keywords:
        return
    for name in list(os.environ):
        if name.startswith(("DCA_", "GOOGLE_")) or name in ("CHAOS", "CHAOS_SEED"):
            monkeypatch.delenv(name)
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError(f"Network use in an offline test: {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    def build(**overrides: object) -> Settings:
        paths = {
            "executives": str(EXECUTIVES),
            "reports_db": str(tmp_path / "reports.sqlite"),
            "trace_file": str(tmp_path / "traces.jsonl"),
        }
        paths.update(overrides.pop("paths", {}))  # type: ignore[arg-type]
        return Settings(_env_file=None, paths=paths, **overrides)

    return build


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def warehouse() -> FakeWarehouse:
    return FakeWarehouse()


@pytest.fixture
def make_api(settings: Settings, warehouse: FakeWarehouse) -> Callable[..., TurnAPI]:
    def build(llm: ScriptedLLM, *, settings_: Settings | None = None, warehouse_: FakeWarehouse | None = None) -> TurnAPI:
        used = settings_ or settings
        knowledge = SchemaKnowledgeStore()
        return TurnAPI(
            settings=used,
            config_store=JsonConfigStore(Path(used.paths.executives)),
            session_store=InMemorySessionStore(),
            warehouse=warehouse_ or warehouse,
            tracer=JsonlTracer(Path(used.paths.trace_file)),
            knowledge=knowledge,
            agent_loop=AdkAgentLoop(llm.adk_model, knowledge),
        )

    return build


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
