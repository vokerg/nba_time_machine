from __future__ import annotations


class SportsProviderError(RuntimeError):
    """Base error for structured sports-provider failures."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SportsProviderConfigurationError(SportsProviderError):
    """Raised when provider configuration is invalid."""


class SportsProviderRateLimitError(SportsProviderError):
    """Raised when the provider keeps rate-limiting after bounded retries."""


class SportsProviderTimeoutError(SportsProviderError):
    """Raised when provider requests exhaust the timeout retry budget."""


class SportsProviderResponseError(SportsProviderError):
    """Raised when provider output does not match the expected JSON envelope."""
