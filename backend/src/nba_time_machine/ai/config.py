from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nba_time_machine.ai.errors import AIConfigurationError


class AISettings(BaseSettings):
    """Environment-backed configuration for an OpenAI-compatible JSON provider."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore", populate_by_name=True)

    enabled: bool = Field(default=False, validation_alias="AI_ENABLED")
    provider: str = Field(default="openai-compatible", validation_alias="LLM_PROVIDER")
    base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="LLM_BASE_URL"
    )
    model: str = Field(default="", validation_alias="LLM_MODEL")
    api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY")
    timeout_seconds: float = Field(
        default=120.0, gt=0, validation_alias="LLM_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(
        default=1, ge=0, le=5, validation_alias="LLM_MAX_RETRIES"
    )
    debug_logging: bool = Field(
        default=False, validation_alias="LLM_DEBUG_LOGGING"
    )

    def require_ready(self) -> None:
        if not self.enabled:
            return

        missing: list[str] = []
        if self.provider.strip() != "openai-compatible":
            raise AIConfigurationError(
                "LLM_PROVIDER must be 'openai-compatible' for the configured client"
            )
        if not self.base_url.strip():
            missing.append("LLM_BASE_URL")
        if not self.model.strip():
            missing.append("LLM_MODEL")
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            missing.append("LLM_API_KEY")

        if missing:
            raise AIConfigurationError(
                "AI is enabled but required configuration is missing: "
                + ", ".join(missing)
            )


def load_ai_settings() -> AISettings:
    return AISettings()
