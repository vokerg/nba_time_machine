from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from nba_time_machine.ai.config import AISettings
from nba_time_machine.ai.contracts import AIJSONRequest, AIJSONResult, AITokenUsage
from nba_time_machine.ai.errors import (
    AIDisabledError,
    AIProviderError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)

logger = logging.getLogger(__name__)

OutputT = TypeVar("OutputT", bound=BaseModel)
Sleep = Callable[[float], Awaitable[None]]


class OpenAICompatibleJSONClient:
    """Async boundary for schema-validated OpenAI-compatible JSON completions."""

    def __init__(
        self,
        settings: AISettings,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.timeout_seconds,
        )

    async def __aenter__(self) -> OpenAICompatibleJSONClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def complete_json(
        self,
        request: AIJSONRequest,
        output_model: type[OutputT],
    ) -> AIJSONResult[OutputT]:
        if not self._settings.enabled:
            raise AIDisabledError("AI features are disabled")
        self._settings.require_ready()

        headers = {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(request)
        max_attempts = self._settings.max_retries + 1

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._http.post(
                    "/chat/completions", headers=headers, json=payload
                )
            except httpx.TimeoutException as exc:
                self._log_status(request, attempt, "timeout")
                if attempt < max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise AITimeoutError(
                    "AI provider request timed out after bounded retries"
                ) from exc
            except httpx.HTTPError as exc:
                self._log_status(request, attempt, "network_error")
                raise AIProviderError("AI provider network request failed") from exc

            if response.status_code == 429:
                self._log_status(request, attempt, "rate_limited")
                if attempt < max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise AIRateLimitError(
                    "AI provider rate limit persisted after bounded retries",
                    status_code=response.status_code,
                )

            if response.status_code >= 500:
                self._log_status(request, attempt, "provider_error")
                if attempt < max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise AIProviderError(
                    "AI provider failed after bounded retries",
                    status_code=response.status_code,
                )

            if response.status_code >= 400:
                self._log_status(request, attempt, "provider_rejected")
                raise AIProviderError(
                    "AI provider rejected the request",
                    status_code=response.status_code,
                )

            self._log_status(request, attempt, "ok")
            return self._parse_response(response, request, output_model)

        raise AIProviderError("AI provider request failed without a terminal response")

    def _build_payload(self, request: AIJSONRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        return {
            "model": self._settings.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }

    def _parse_response(
        self,
        response: httpx.Response,
        request: AIJSONRequest,
        output_model: type[OutputT],
    ) -> AIJSONResult[OutputT]:
        try:
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content must be a string")
            decoded = json.loads(content)
            output = output_model.model_validate(decoded)
            usage = self._parse_usage(payload.get("usage"))
            model = payload.get("model") or self._settings.model
            if not isinstance(model, str) or not model:
                raise TypeError("model must be a non-empty string")
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise AIResponseValidationError(
                "AI provider returned output that failed schema validation"
            ) from exc

        return AIJSONResult[OutputT](
            output=output,
            model=model,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            usage=usage,
        )

    @staticmethod
    def _parse_usage(value: object) -> AITokenUsage | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("usage must be an object")
        return AITokenUsage.model_validate(value)

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(0.25 * (2 ** (attempt - 1)), 2.0)

    def _log_status(self, request: AIJSONRequest, attempt: int, status: str) -> None:
        level = logging.DEBUG if self._settings.debug_logging else logging.INFO
        logger.log(
            level,
            "ai_provider_request",
            extra={
                "ai_use_case": request.use_case,
                "ai_model": self._settings.model,
                "ai_attempt": attempt,
                "ai_status": status,
            },
        )
