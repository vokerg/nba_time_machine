from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database-backed operation is requested without a URL."""


class DatabaseSettings(BaseSettings):
    """Database URLs are loaded lazily; importing the app never requires Postgres."""

    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    direct_database_url: str | None = Field(
        default=None,
        validation_alias="DIRECT_DATABASE_URL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_configured(self) -> bool:
        return bool(self.database_url and self.database_url.strip())

    def application_sqlalchemy_url(self) -> str:
        return _normalize_postgres_url(
            self._require_url(self.database_url, "DATABASE_URL")
        )

    def migration_sqlalchemy_url(self) -> str:
        raw_url = self.direct_database_url or self.database_url
        return _normalize_postgres_url(
            self._require_url(raw_url, "DIRECT_DATABASE_URL or DATABASE_URL")
        )

    @staticmethod
    def _require_url(value: str | None, name: str) -> str:
        if value is None or not value.strip():
            raise DatabaseNotConfiguredError(
                f"{name} is required for this database operation"
            )
        return value.strip()


def _normalize_postgres_url(url: str) -> str:
    """Normalize common Postgres URLs to SQLAlchemy's async Psycopg dialect."""

    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgresql+psycopg://"):
        return url

    raise ValueError(
        "Database URL must use postgres://, postgresql://, "
        "or postgresql+psycopg://"
    )
