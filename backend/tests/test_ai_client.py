from __future__ import annotations

import logging

import httpx
import pytest
from pydantic import BaseModel

from nba_time_machine.ai import (
    AIConfigurationError,
    AIDisabledError,
    AIJSONRequest,
    AIProviderError,
    AIRateLimitError,
    AIResponseValidationError,
    AISettings,
    AITimeoutError,
    OpenAICompatibleJSONClient,
    load_ai_settings,
)


class Summary(BaseModel):
    headline: str
    confidence: float


def settings(**overrides: object) -> AISettings:
    values: dict[str, object] = {
        "AI_ENABLED": True,
        "LLM_PROVIDER": "openai-compatible",
        "LLM_BASE_URL": "https://provider.example",
        "LLM_MODEL": "example-model",
        "LLM_API_KEY": "super-secret-key",
        "LLM_TIMEOUT_SECONDS": 5,
        "LLM_MAX_RETRIES": 1,
    }
    values.update(overrides)
    return AISettings(**values)


def request(prompt: str = "sensitive source body") -> AIJSONRequest:
    return AIJSONRequest(
        use_case="test-summary",
        prompt=prompt,
        prompt_version="prompt-v1",
        schema_version="summary-v1",
    )


def test_load_ai_settings_reads_documented_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://alternate-provider.example")
    monkeypatch.setenv("LLM_MODEL", "alternate-model")
    monkeypatch.setenv("LLM_API_KEY", "environment-secret")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_DEBUG_LOGGING", "true")

    loaded = load_ai_settings()

    assert loaded.enabled is True
    assert loaded.provider == "openai-compatible"
    assert loaded.base_url == "https://alternate-provider.example"
    assert loaded.model == "alternate-model"
    assert loaded.api_key is not None
    assert loaded.api_key.get_secret_value() == "environment-secret"
    assert loaded.timeout_seconds == 9
    assert loaded.max_retries == 2
    assert loaded.debug_logging is True


@pytest.mark.asyncio
async def test_disabled_client_fails_before_network() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(AISettings(), http_client=http)

    with pytest.raises(AIDisabledError):
        await client.complete_json(request(), Summary)

    assert calls == 0
    await http.aclose()


@pytest.mark.asyncio
async def test_enabled_client_requires_complete_configuration() -> None:
    http = httpx.AsyncClient(base_url="https://provider.example")
    client = OpenAICompatibleJSONClient(
        settings(LLM_API_KEY="", LLM_MODEL=""),
        http_client=http,
    )

    with pytest.raises(AIConfigurationError, match="LLM_MODEL, LLM_API_KEY"):
        await client.complete_json(request(), Summary)

    await http.aclose()


@pytest.mark.asyncio
async def test_successful_json_response_is_schema_validated() -> None:
    seen: httpx.Request | None = None

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = req
        return httpx.Response(
            200,
            json={
                "model": "provider-model-v2",
                "choices": [
                    {
                        "message": {
                            "content": '{"headline":"Safe summary","confidence":0.9}'
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                    "total_tokens": 18,
                },
            },
        )

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http)
    result = await client.complete_json(request(), Summary)

    assert result.output.headline == "Safe summary"
    assert result.output.confidence == 0.9
    assert result.model == "provider-model-v2"
    assert result.prompt_version == "prompt-v1"
    assert result.schema_version == "summary-v1"
    assert result.usage is not None and result.usage.total_tokens == 18
    assert seen is not None
    assert seen.headers["authorization"] == "Bearer super-secret-key"
    assert seen.url.path == "/chat/completions"
    assert b'"response_format":{"type":"json_object"}' in seen.content
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"headline":"missing confidence"}',
    ],
)
async def test_malformed_or_schema_invalid_output_fails_closed(content: str) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http)

    with pytest.raises(AIResponseValidationError):
        await client.complete_json(request(), Summary)

    await http.aclose()


@pytest.mark.asyncio
async def test_rate_limit_retries_are_bounded_then_succeed() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"headline":"Recovered","confidence":1.0}'
                        }
                    }
                ]
            },
        )

    async def sleep(delay: float) -> None:
        delays.append(delay)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http, sleep=sleep)
    result = await client.complete_json(request(), Summary)

    assert result.output.headline == "Recovered"
    assert attempts == 2
    assert delays == [0.25]
    await http.aclose()


@pytest.mark.asyncio
async def test_retry_budget_exhaustion_maps_rate_limit_error() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429)

    async def no_sleep(_: float) -> None:
        return None

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http, sleep=no_sleep)

    with pytest.raises(AIRateLimitError) as exc_info:
        await client.complete_json(request(), Summary)

    assert exc_info.value.status_code == 429
    assert attempts == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_timeout_retries_are_bounded_and_mapped() -> None:
    attempts = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("provider timeout", request=req)

    async def no_sleep(_: float) -> None:
        return None

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http, sleep=no_sleep)

    with pytest.raises(AITimeoutError):
        await client.complete_json(request(), Summary)

    assert attempts == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_non_retryable_provider_error_does_not_retry() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http)

    with pytest.raises(AIProviderError) as exc_info:
        await client.complete_json(request(), Summary)

    assert exc_info.value.status_code == 400
    assert attempts == 1
    await http.aclose()


@pytest.mark.asyncio
async def test_logs_do_not_include_prompt_api_key_or_raw_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_prompt = "TOP SECRET ARTICLE BODY"
    raw_response = "RAW SECRET MODEL OUTPUT"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": raw_response}}]},
        )

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = OpenAICompatibleJSONClient(settings(), http_client=http)

    with caplog.at_level(logging.INFO), pytest.raises(AIResponseValidationError):
        await client.complete_json(request(secret_prompt), Summary)

    rendered = caplog.text
    assert secret_prompt not in rendered
    assert "super-secret-key" not in rendered
    assert raw_response not in rendered
    await http.aclose()
