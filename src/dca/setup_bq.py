"""`uv run setup-bq`: makes the threshold views again (ADR 0005), with `CREATE OR REPLACE`.

It runs `scripts/threshold-views.sql` through the `bq` CLI, so it uses your own `gcloud`
account (the owner of the project). The chat uses ADC as `dca-agent`, which can only read the
views. In the BigQuery sandbox the views expire after 60 days: run this command again.
"""

import shutil
import subprocess
import sys

from dca.config import ROOT, Settings

SQL_FILE = ROOT / "scripts" / "threshold-views.sql"


def fail(message: str) -> None:
    print(f"setup-bq: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    settings = Settings()
    project = settings.google_cloud_project
    if not project:
        fail("Set GOOGLE_CLOUD_PROJECT in .env. Use the project of scripts/setup-gcp.sh.")
    bq = shutil.which("bq")
    if bq is None:
        fail("The bq command is not available. Install the Google Cloud CLI, then run 'gcloud auth login'.")
    sql = SQL_FILE.read_text(encoding="utf-8")
    sql = sql.replace("PROJECT_ID", project).replace(".dca_views.", f".{settings.warehouse.threshold_dataset}.")
    result = subprocess.run(
        [bq, f"--project_id={project}", "query", "--use_legacy_sql=false"],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no detail"]
        fail(
            "Your gcloud account could not make the threshold views. It must be an owner of the project "
            f"{project}, and scripts/setup-gcp.sh must have made the dataset. Detail: {detail[0]}"
        )
    print(f"Done. The threshold views are in {project}.{settings.warehouse.threshold_dataset}.")
