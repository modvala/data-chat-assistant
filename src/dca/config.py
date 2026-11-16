"""Settings of the prototype (P17).

The starting values are in `config/defaults.toml`, not in the code. An environment
variable or `.env` overrides a value, for example `DCA_MODEL` or `DCA_BUDGET__LLM_CALLS`.
"""

import os
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_FILE = Path(os.environ.get("DCA_CONFIG_FILE", ROOT / "config" / "defaults.toml"))


class Paths(BaseModel):
    executives: Path
    reports_db: Path
    trace_file: Path


class WarehouseSettings(BaseModel):
    source_dataset: str
    threshold_dataset: str
    threshold_k: int


class Budget(BaseModel):
    llm_calls: int
    llm_tokens: int
    query_bytes: int
    turn_bytes: int
    wall_time_s: float
    corrections: int


class Retry(BaseModel):
    llm_retries: int
    bq_retries: int
    backoff_min_s: float
    backoff_max_s: float


class Timeout(BaseModel):
    llm_call_s: float
    bq_job_s: float


class Confirmation(BaseModel):
    ttl_s: int
    undo_window_h: int


class Limits(BaseModel):
    rows_to_llm: int
    sql_limit: int
    table_rows_shown: int
    trace_rows: int
    conversation_tokens: int
    input_max_chars: int
    classifier_questions: int


class Cost(BaseModel):
    llm_usd_per_1k_tokens: float
    bq_usd_per_tib: float


class Display(BaseModel):
    header_max_brands: int
    preview_max_items: int


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DCA_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        toml_file=DEFAULTS_FILE,
    )

    model: str
    fallback_model: str
    persona_version: str
    google_api_key: str = Field("", validation_alias=AliasChoices("GOOGLE_API_KEY", "google_api_key"))
    google_cloud_project: str = Field(
        "", validation_alias=AliasChoices("GOOGLE_CLOUD_PROJECT", "google_cloud_project")
    )
    chaos: str = Field("", validation_alias=AliasChoices("CHAOS", "chaos"))
    chaos_seed: int | None = Field(None, validation_alias=AliasChoices("CHAOS_SEED", "chaos_seed"))

    paths: Paths
    warehouse: WarehouseSettings
    budget: Budget
    retry: Retry
    timeout: Timeout
    confirmation: Confirmation
    limits: Limits
    cost: Cost
    display: Display

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings, TomlConfigSettingsSource(settings_cls))
