"""Settings loaded from C:\\Jarvis\\.env via pydantic-settings. Secrets live only here."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from typing import Any

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/jarvis/config.py -> project root is two levels above backend/
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    host: str = "127.0.0.1"
    port: int = 8765

    # Planner LLM
    llm_provider: str = "mock"  # anthropic | openai | mock
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    # Optional prices (USD per million tokens) used for est_cost; unset -> cost unknown.
    llm_input_cost_per_mtok: float | None = None
    llm_output_cost_per_mtok: float | None = None

    # Notion
    notion_token: SecretStr | None = None
    notion_parent_page_id: str = ""
    notion_database_id: str = ""

    # Voice
    stt_model: str = "base"
    tts_enabled: bool = True

    # Execution
    dry_run: bool = False
    approval_timeout_s: float = 120.0
    step_timeout_s: float = 45.0
    max_retries: int = 2

    # UFO²
    ufo_enabled: bool = True
    ufo_timeout_s: float = 180.0

    data_dir: Path = ROOT_DIR / "data"

    @model_validator(mode="before")
    @classmethod
    def _empty_means_unset(cls, data: Any) -> Any:
        """KEY= (empty) in .env falls back to the default instead of failing validation."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and v.strip() == "")}
        return data

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def ufo_dir(self) -> Path:
        return ROOT_DIR / "vendor" / "UFO"

    @property
    def frontend_dist(self) -> Path:
        return ROOT_DIR / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
