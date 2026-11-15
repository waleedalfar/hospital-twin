import pytest
from pydantic import ValidationError

from twin.common.config import REPO_ROOT, Settings, get_settings


def make_settings(**overrides: object) -> Settings:
    # _env_file=None keeps a developer's real .env out of unit tests.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_point_at_local_docker_db(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "API_PORT", "GEMINI_API_KEY", "GEMINI_MODEL", "SIM_SEED", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    settings = make_settings()
    assert settings.database_url.get_secret_value() == "postgresql://twin:twin@localhost:5433/twin"
    assert settings.api_port == 8000
    assert settings.gemini_api_key is None
    assert settings.gemini_model is None


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:5432/x")
    monkeypatch.setenv("API_PORT", "9001")
    monkeypatch.setenv("SIM_SEED", "7")
    monkeypatch.setenv("GEMINI_MODEL", "model-from-env")
    settings = make_settings()
    assert settings.database_url.get_secret_value() == "postgresql://u:p@db.example:5432/x"
    assert settings.api_port == 9001
    assert settings.sim_seed == 7
    assert settings.gemini_model == "model-from-env"


def test_invalid_port_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "70000")
    with pytest.raises(ValidationError):
        make_settings()


def test_secrets_are_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:hunter2@h/x")
    monkeypatch.setenv("GEMINI_API_KEY", "key-abc-123")
    settings = make_settings()
    text = repr(settings)
    assert "hunter2" not in text
    assert "key-abc-123" not in text


def test_secret_values_lists_every_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:hunter2@h/x")
    monkeypatch.setenv("GEMINI_API_KEY", "key-abc-123")
    assert make_settings().secret_values() == ["postgresql://u:hunter2@h/x", "key-abc-123"]
    monkeypatch.delenv("GEMINI_API_KEY")
    assert make_settings().secret_values() == ["postgresql://u:hunter2@h/x"]


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_repo_root_is_the_project_root() -> None:
    assert (REPO_ROOT / "PROMPT.md").is_file()
    assert (REPO_ROOT / "backend" / "pyproject.toml").is_file()


def test_env_example_lists_every_setting() -> None:
    """CLAUDE.md §1.9: `.env.example` lists every variable."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    listed = {line.split("=", 1)[0].strip() for line in example.splitlines() if "=" in line and line[0] != "#"}
    expected = {name.upper() for name in Settings.model_fields}
    assert expected <= listed, f"missing from .env.example: {sorted(expected - listed)}"
