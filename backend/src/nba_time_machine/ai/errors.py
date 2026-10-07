from __future__ import annotations


class AIClientError(RuntimeError):
    """Base error for provider-neutral AI client failures."""


class AIDisabledError(AIClientError):
    """Raised when an AI request is attempted while AI features are disabled."""


class AIConfigurationError(AIClientError):
    """Raised when enabled AI features are missing required configuration."""


class AIProviderError(AIClientError):
    """Raised when the upstream OpenAI-compatible provider rejects or fails a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AIRateLimitError(AIProviderError):
    """Raised when the upstream provider rate-limits the request."""


class AITimeoutError(AIProviderError):
    """Raised after provider timeouts exhaust the configured retry budget."""


class AIResponseValidationError(AIClientError):
    """Raised when provider output cannot be safely validated as the requested schema."""
