"""The core imports no framework, warehouse, store or tracing SDK module (HLD 4.3, P6)."""

import ast
import json
import tomllib
from pathlib import Path

from dca.config import DEFAULTS_FILE, ROOT

CORE = ROOT / "src" / "dca" / "core"
FORBIDDEN = ("google.adk", "google.genai", "google.cloud", "google.api_core", "sqlite3", "opentelemetry")


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_imports_no_adapter_module() -> None:
    files = sorted(CORE.glob("*.py"))
    assert files
    for path in files:
        bad = [name for name in imports(path) if name.startswith(FORBIDDEN)]
        assert not bad, f"{path.name} imports {bad}"


def test_executives_file_has_the_ceo_and_two_managers_with_different_brands() -> None:
    data = json.loads((ROOT / "executives.json").read_text(encoding="utf-8"))["executives"]
    assert [item["role"] for item in data].count("ceo") == 1
    managers = [item for item in data if item["role"] == "manager"]
    assert len(managers) >= 2
    assert set(managers[0]["brands"]).isdisjoint(managers[1]["brands"])


def test_starting_values_are_in_the_configuration_file() -> None:
    defaults = tomllib.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    for section in ("budget", "retry", "timeout", "confirmation", "limits"):
        assert defaults[section], section
    assert defaults["model"] and defaults["fallback_model"]
