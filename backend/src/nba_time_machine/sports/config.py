from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nba_time_machine.sports.errors import SportsProviderConfigurationError


class SportsProviderSettings(BaseSettings):
    """Configuration for the first structured NBA provider."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    provider: str = Field(
        default="thesportsdb",
        validation_alias="SPORTS_PROVIDER",
    )
    base_url: str = Field(
        default="https://www.thesportsdb.com/api/v1/json",
        validation_alias="THESPORTSDB_BASE_URL",
    )
    api_key: SecretStr = Field(
        default=SecretStr("123"),
        validation_alias="THESPORTSDB_API_KEY",
    )
    nba_league_id: str = Field(
        default="4387",
        validation_alias="THESPORTSDB_NBA_LEAGUE_ID",
    )
    timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        validation_alias="SPORTS_PROVIDER_TIMEOUT_SECONDS",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias="SPORTS_PROVIDER_MAX_RETRIES",
    )

    def require_ready(self) -> None:
        if self.provider.strip() != "thesportsdb":
            raise SportsProviderConfigurationError(
                "SPORTS_PROVIDER must be 'thesportsdb' for this adapter"
            )
        if not self.base_url.strip():
            raise SportsProviderConfigurationError(
                "THESPORTSDB_BASE_URL must not be empty"
            )
        if not self.api_key.get_secret_value().strip():
            raise SportsProviderConfigurationError(
                "THESPORTSDB_API_KEY must not be empty"
            )
        if not self.nba_league_id.strip():
            raise SportsProviderConfigurationError(
                "THESPORTSDB_NBA_LEAGUE_ID must not be empty"
            )


def load_sports_provider_settings() -> SportsProviderSettings:
    return SportsProviderSettings()
