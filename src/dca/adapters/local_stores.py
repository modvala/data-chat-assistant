"""Local adapters of the `SessionStore`, `ConfigStore` and `KnowledgeStore` ports."""

import json
from pathlib import Path

from dca.core import schema
from dca.core.ports import ExecutiveEntry
from dca.core.state import SessionState


class InMemorySessionStore:
    """Keeps a copy of each state, so that a Turn works on what it loaded (P21)."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}

    def load(self, session_id: str) -> SessionState | None:
        raw = self._states.get(session_id)
        return SessionState.model_validate_json(raw) if raw else None

    def save(self, state: SessionState) -> None:
        self._states[state.session_id] = state.model_dump_json()


class JsonConfigStore:
    """The access mapping in `executives.json` (A1). The file is read on each call (P17)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _entries(self) -> dict[str, ExecutiveEntry]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        entries = {}
        for item in data["executives"]:
            brands = None if item["role"] == "ceo" else tuple(item["brands"])
            entries[item["id"]] = ExecutiveEntry(item["id"], item["role"], brands)
        return entries

    def access(self, executive_id: str) -> ExecutiveEntry | None:
        return self._entries().get(executive_id)

    def executive_ids(self) -> list[str]:
        return sorted(self._entries())


class SchemaKnowledgeStore:
    """The schema description, made from the scoped view definitions."""

    def schema(self) -> str:
        return schema.describe()
