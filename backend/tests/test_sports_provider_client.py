from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from nba_time_machine.sports.config import SportsProviderSettings
from nba_time_machine.sports.errors import (
    SportsProviderRateLimitError,
    SportsProviderResponseError,
)
from nba_time_machine.sports.thesportsdb import TheSportsDBClient


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_retries: int = 0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> TheSportsDBClient:
    settings = SportsProviderSettings(
        base_url="https://sports.example.test/api/v1/json",
        api_key="test-key",
        nba_league_id="4387",
        max_retries=max_retries,
    )
    http_client = httpx.AsyncClient(
        base_url=settings.base_url,
        transport=httpx.MockTransport(handler),
    )
    kwargs = {"http_client": http_client}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return TheSportsDBClient(settings, **kwargs)


@pytest.mark.asyncio
async def test_next_events_use_expected_keyed_path_and_league() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/json/test-key/eventsnextleague.php"
        assert request.url.params["id"] == "4387"
        return httpx.Response(
            200,
            json={
                "events": [
                    {
                        "idEvent": "2601626",
                        "idLeague": "4387",
                        "idHomeTeam": "134873",
                        "idAwayTeam": "134886",
                    }
                ]
            },
        )

    client = _client(handler)
    try:
        events = await client.next_nba_events()
    finally:
        await client.aclose()

    assert events[0]["idEvent"] == "2601626"


@pytest.mark.asyncio
async def test_team_lookup_rejects_missing_team() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"teams": None})

    client = _client(handler)
    try:
        with pytest.raises(SportsProviderResponseError):
            await client.team("134873")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_retries_are_bounded() -> None:
    attempts = 0
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"error": "rate limited"})

    client = _client(handler, max_retries=2, sleep=sleep)
    try:
        with pytest.raises(SportsProviderRateLimitError) as exc:
            await client.next_nba_events()
    finally:
        await client.aclose()

    assert exc.value.status_code == 429
    assert attempts == 3
    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_non_object_json_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(["not", "an", "object"]).encode(),
            headers={"content-type": "application/json"},
        )

    client = _client(handler)
    try:
        with pytest.raises(SportsProviderResponseError):
            await client.next_nba_events()
    finally:
        await client.aclose()


def test_default_public_development_key_is_configurable() -> None:
    settings = SportsProviderSettings(_env_file=None)

    assert settings.provider == "thesportsdb"
    assert settings.nba_league_id == "4387"
    assert settings.api_key.get_secret_value() == "123"
