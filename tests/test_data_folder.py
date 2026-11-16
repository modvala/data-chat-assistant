"""The runtime files go to one data folder: the same layout as the Docker setup of #40."""

import json
import tomllib
from pathlib import Path

from dca.adapters.otel_tracer import JsonlTracer
from dca.adapters.sqlite_reports import SQLiteReportStore
from dca.config import DEFAULTS_FILE


def test_runtime_files_are_in_the_data_folder_by_default() -> None:
    paths = tomllib.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))["paths"]
    assert Path(paths["reports_db"]).parent == Path("data")
    assert Path(paths["trace_file"]).parent == Path("data")


def test_report_store_makes_a_missing_data_folder(tmp_path: Path) -> None:
    path = tmp_path / "data" / "dca_reports.sqlite"

    SQLiteReportStore(path)

    assert path.exists()


def test_tracer_makes_a_missing_data_folder(tmp_path: Path) -> None:
    path = tmp_path / "data" / "dca_traces.jsonl"
    tracer = JsonlTracer(path)

    with tracer.span("turn"):
        tracer.log("test.event")

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record.get("event") or record.get("name") for record in records] == ["test.event", "turn"]
