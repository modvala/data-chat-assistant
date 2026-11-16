"""`uv run setup-bq` with a fake `bq` command (ADR 0005)."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from dca import setup_bq


@pytest.fixture(autouse=True)
def clean_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .env of the developer
    monkeypatch.setattr(setup_bq.shutil, "which", lambda name: "/usr/bin/bq")


def fake_run(returncode: int, calls: list[dict[str, Any]], stderr: str = "") -> Any:
    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess:
        calls.append({"command": command, **options})
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr=stderr)

    return run


def test_ac_r2_3_setup_bq_makes_the_views_with_the_bq_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    monkeypatch.setattr(setup_bq.subprocess, "run", fake_run(0, calls))

    setup_bq.main()

    assert calls[0]["command"] == ["/usr/bin/bq", "--project_id=my-proj", "query", "--use_legacy_sql=false"]
    sql = calls[0]["input"]
    assert "CREATE OR REPLACE VIEW `my-proj.dca_views.customer_sales_threshold`" in sql
    assert "PROJECT_ID" not in sql
    assert "Done." in capsys.readouterr().out


def test_ac_r2_3_setup_bq_stops_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    monkeypatch.setattr(setup_bq.subprocess, "run", fake_run(1, [], stderr="Access Denied: Dataset my-proj:dca_views"))

    with pytest.raises(SystemExit) as stop:
        setup_bq.main()

    assert stop.value.code == 1
    message = capsys.readouterr().err
    assert "could not make the threshold views" in message and "Access Denied" in message


def test_ac_r2_3_setup_bq_needs_a_project(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        setup_bq.main()
    assert "GOOGLE_CLOUD_PROJECT" in capsys.readouterr().err
