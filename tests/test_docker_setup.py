"""The Docker setup of #40 keeps the decisions of the issue.

The image build and the runs are manual checks. These tests catch drift between the
Docker files and the configuration, and stop a secret from going into the image.
"""

import tomllib
from pathlib import Path, PurePosixPath

import yaml

from dca.config import DEFAULTS_FILE, ROOT

DOCKERFILE = ROOT / "docker" / "Dockerfile"


def _service() -> dict:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    return compose["services"]["dca"]


def _instruction(prefix: str) -> str:
    """The value of the last Dockerfile line that starts with the prefix."""
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    values = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    assert values, f"docker/Dockerfile has no line '{prefix}'"
    return values[-1]


def _workdir() -> PurePosixPath:
    return PurePosixPath(_instruction("WORKDIR "))


def test_the_dockerfile_is_not_in_the_root() -> None:
    # A root Dockerfile would replace the buildpacks of `gcloud run deploy --source` (#5).
    assert DOCKERFILE.exists()
    assert not (ROOT / "Dockerfile").exists()
    assert _service()["build"] == {"context": ".", "dockerfile": "docker/Dockerfile"}


def test_secrets_and_runtime_files_stay_out_of_the_image() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in [".env*", ".venv", "data", "**/__pycache__"]:
        assert entry in ignored


def test_the_data_folder_of_the_host_is_the_data_folder_of_the_config() -> None:
    paths = tomllib.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))["paths"]
    workdir = _workdir()
    mounts = {mount["target"]: mount for mount in _service()["volumes"]}

    data = mounts[str(workdir / Path(paths["reports_db"]).parent.as_posix())]
    assert data["type"] == "bind"
    assert data["source"] == "./data"
    assert Path(paths["trace_file"]).parent == Path(paths["reports_db"]).parent

    executives = mounts[str(workdir / paths["executives"])]
    assert executives["type"] == "bind"
    assert executives["source"] == f"./{paths['executives']}"
    assert executives["read_only"] is True


def test_the_gcloud_credentials_are_in_a_named_volume() -> None:
    service = _service()
    mounts = {mount["target"]: mount for mount in service["volumes"]}

    gcloud = mounts[_instruction("ENV CLOUDSDK_CONFIG=")]
    assert gcloud["type"] == "volume"
    assert gcloud["source"] == "gcloud-config"


def test_the_service_is_interactive_and_reads_the_env_file() -> None:
    service = _service()
    assert service["stdin_open"] is True
    assert service["tty"] is True
    assert service["env_file"] == [".env"]
    # One source for the project: setup-gcp.sh falls back to GOOGLE_CLOUD_PROJECT.
    assert "environment" not in service
