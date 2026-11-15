"""Runtime configuration, read from environment variables and the repo-root `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """All settings the backend reads. Every field is listed in `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr = Field(
        default=SecretStr("postgresql://twin:twin@localhost:5433/twin"),
        description="TimescaleDB / Tiger Cloud connection string.",
    )
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    sim_seed: int = 20261114
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    # A local model (Ollama) used when Gemini fails or hangs; no key needed, e.g. OLLAMA_URL=http://ollama:11434
    ollama_url: str | None = None
    ollama_model: str | None = None
    sim_warmup_hours: float = Field(default=72.0, ge=0)
    sim_speed: int = 1
    sim_autostart: bool = True
    sim_reset_on_start: bool = True
    sim_debug: bool = False
    ml_enabled: bool = True
    agent_enabled: bool = True
    agent_llm_min_interval_s: float = 20.0
    synthea_java: str | None = None
    synthea_population: int = Field(default=3000, ge=1)
    synthea_seed: int = 20261114

    def secret_values(self) -> list[str]:
        """Plain values that must never appear in logs."""
        values = [self.database_url.get_secret_value()]
        if self.gemini_api_key is not None:
            values.append(self.gemini_api_key.get_secret_value())
        return [value for value in values if value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings instance."""
    return Settings()
