import pytest

from nba_time_machine.db.config import (
    DatabaseNotConfiguredError,
    DatabaseSettings,
)


def test_database_settings_are_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DIRECT_DATABASE_URL", raising=False)

    settings = DatabaseSettings(_env_file=None)

    assert settings.is_configured is False
    with pytest.raises(DatabaseNotConfiguredError):
        settings.application_sqlalchemy_url()


def test_urls_use_async_psycopg_and_direct_url_for_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://app:secret@db.example/app",
    )
    monkeypatch.setenv(
        "DIRECT_DATABASE_URL",
        "postgres://admin:secret@direct.example/app",
    )

    settings = DatabaseSettings(_env_file=None)

    assert (
        settings.application_sqlalchemy_url()
        == "postgresql+psycopg://app:secret@db.example/app"
    )
    assert (
        settings.migration_sqlalchemy_url()
        == "postgresql+psycopg://admin:secret@direct.example/app"
    )
