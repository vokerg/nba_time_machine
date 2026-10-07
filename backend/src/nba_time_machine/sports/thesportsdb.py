from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from nba_time_machine.sports.config import SportsProviderSettings
from nba_time_machine.sports.errors import (
    SportsProviderError,
    SportsProviderRateLimitError,
    SportsProviderResponseError,
    SportsProviderTimeoutError,
)

Sleep = Callable[[float], Awaitable[None]]


class TheSportsDBClient:
    """Small async boundary around the documented TheSportsDB v1 API."""

    def __init__(
        self,
        settings: SportsProviderSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        settings.require_ready()
        self._settings = settings
        self._sleep = sleep
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/") + "/",
            timeout=settings.timeout_seconds,
        )

    async def __aenter__(self) -> TheSportsDBClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def next_nba_events(self) -> list[dict[str, Any]]:
        payload = await self._get(
            "eventsnextleague.php",
            {"id": self._settings.nba_league_id},
        )
        return self._list_field(payload, "events")

    async def previous_nba_events(self) -> list[dict[str, Any]]:
        payload = await self._get(
            "eventspastleague.php",
            {"id": self._settings.nba_league_id},
        )
        return self._list_field(payload, "events")

    async def events_on_date(self, date_value: str) -> list[dict[str, Any]]:
        payload = await self._get(
            "eventsday.php",
            {"d": date_value, "l": self._settings.nba_league_id},
        )
        return self._list_field(payload, "events")

    async def team(self, team_id: str) -> dict[str, Any]:
        payload = await self._get("lookupteam.php", {"id": team_id})
        teams = self._list_field(payload, "teams")
        if not teams:
            raise SportsProviderResponseError(
                f"TheSportsDB returned no team for id {team_id}"
            )
        return teams[0]

    async def team_players(self, team_id: str) -> list[dict[str, Any]]:
        payload = await self._get("lookup_all_players.php", {"id": team_id})
        return self._list_field(payload, "player")

    async def event_stats(self, event_id: str) -> list[dict[str, Any]]:
        payload = await self._get("lookupeventstats.php", {"id": event_id})
        return self._list_field(payload, "eventstats")

    async def player_stats(self, player_id: str) -> list[dict[str, Any]]:
        payload = await self._get("lookupplayerstats.php", {"id": player_id})
        return self._list_field(payload, "playerstats")

    async def _get(
        self,
        endpoint: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        max_attempts = self._settings.max_retries + 1
        path = (
            f"/{self._settings.api_key.get_secret_value().strip()}/"
            f"{endpoint}"
        )

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                if attempt < max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise SportsProviderTimeoutError(
                    "TheSportsDB request timed out after bounded retries"
                ) from exc
            except httpx.HTTPError as exc:
                raise SportsProviderError(
                    "TheSportsDB network request failed"
                ) from exc

            if response.status_code == 429:
                if attempt < max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise SportsProviderRateLimitError(
                    "TheSportsDB rate limit persisted after bounded retries",
                    status_code=response.status_code,
                )

            if response.status_code >= 500:
                if attempt < max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise SportsProviderError(
                    "TheSportsDB failed after bounded retries",
                    status_code=response.status_code,
                )

            if response.status_code >= 400:
                raise SportsProviderError(
                    "TheSportsDB rejected the request",
                    status_code=response.status_code,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise SportsProviderResponseError(
                    "TheSportsDB returned invalid JSON"
                ) from exc

            if not isinstance(payload, dict):
                raise SportsProviderResponseError(
                    "TheSportsDB returned a non-object JSON payload"
                )
            return payload

        raise SportsProviderError(
            "TheSportsDB request failed without a terminal response"
        )

    @staticmethod
    def _list_field(
        payload: dict[str, Any],
        field: str,
    ) -> list[dict[str, Any]]:
        value = payload.get(field)
        if value is None:
            return []
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise SportsProviderResponseError(
                f"TheSportsDB field {field!r} was not a list of objects"
            )
        return value

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(0.25 * (2 ** (attempt - 1)), 2.0)
