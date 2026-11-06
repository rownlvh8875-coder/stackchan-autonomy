"""Safe defaults with explicit environment opt-ins; YAML never contains secrets."""

from pathlib import Path

import yaml
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import StrictModel


def yaml_mapping(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a mapping")
    return data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STACKCHAN_", env_file=".env", extra="ignore", allow_inf_nan=False
    )
    cloud_enabled: bool = False
    image_transmission: bool = False
    audio_transmission: bool = False
    hardware_enabled: bool = False
    dry_run: bool = True
    openai_model: str | None = None
    api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENAI_API_KEY", exclude=True, repr=False
    )
    observe_interval_s: float = Field(default=30, ge=0.01)
    max_unchanged_interval_s: float = Field(default=300, gt=0)
    cooldown_s: float = Field(default=1, ge=0)
    speech_cooldown_s: float = Field(default=300, ge=0)
    command_interval_s: float = Field(default=1, ge=0)
    operation_timeout_s: float = Field(default=15, gt=0, le=120)
    max_step_deg: float = Field(default=15, gt=0, le=15)
    yaw_min: float = Field(default=-90, ge=-90, le=90)
    yaw_max: float = Field(default=90, ge=-90, le=90)
    pitch_min: float = Field(default=5, ge=5, le=85)
    pitch_max: float = Field(default=85, ge=5, le=85)
    requests_per_minute: int = Field(default=2, ge=1, le=60)
    requests_per_hour: int = Field(default=30, ge=1, le=3600)
    requests_per_day: int = Field(default=100, ge=1, le=86400)
    queue_size: int = Field(default=64, ge=1, le=1000)
    history_size: int = Field(default=100, ge=1, le=10000)
    memory_path: Path | None = None
    state_path: Path = Path(".local/autonomy.sqlite3")
    control_resource: str = Field(default="stackchan:default", min_length=1, max_length=200)
    lease_ttl_s: float = Field(default=10, ge=0.1, le=300)
    budget_namespace: str = Field(default="openai:default", min_length=1, max_length=200)
    mcp_url: str = "http://127.0.0.1:8767/mcp"

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return env_settings, dotenv_settings, init_settings, file_secret_settings

    @model_validator(mode="after")
    def valid_ranges(self):
        if self.yaw_min >= self.yaw_max or self.pitch_min >= self.pitch_max:
            raise ValueError("angle lower bounds must precede upper bounds")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        data = yaml_mapping(path)
        unknown = set(data) - set(cls.model_fields)
        if unknown or "api_key" in data:
            raise ValueError("unknown settings or secret in YAML")
        return cls(**data)


class Personality(StrictModel):
    language: str = "ko"
    instructions: tuple[str, ...]


def load_personality(path: str | Path) -> Personality:
    return Personality.model_validate(yaml_mapping(path))
