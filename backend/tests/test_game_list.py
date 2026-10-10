"""Service and HTTP regression tests for the spoiler-safe historical slate."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from nba_time_machine.api.game_list import get_game_list_service
from nba_time_machine.main import app
from nba_time_machine.spoilers.game_list import GameListService, nba_day_bounds
from nba_time_machine.spoilers.policy import GameField, GameFieldName
from nba_time_machine.spoilers.service import TrustedGameSnapshot
from nba_time_machine.temporal.timeline import TimelineNotInitializedError, TimelineState

PROFILE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
FIRST = UUID("11111111-1111-4111-8111-111111111111")
SECOND = UUID("22222222-2222-4222-8222-222222222222")
HIDDEN = UUID("33333333-3333-4333-8333-333333333333")
DAY = date(2026, 10, 8)
CURSOR = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
TIP = datetime(2026, 10, 9, 0, 30, tzinfo=timezone.utc)  # Oct 8 20:30 ET
FINAL = TIP + timedelta(hours=3)


class Clock:
    def __init__(self) -> None:
        self.cursor = CURSOR

    async def resume(self, profile_id: UUID) -> TimelineState:
        if profile_id != PROFILE:
            raise TimelineNotInitializedError("timeline is not initialized")
        return TimelineState(profile_id, self.cursor, CURSOR, CURSOR)


class Slate:
    def __init__(self) -> None:
        self.calls = []

    async def game_ids_on_date(self, *, slate_date: date, time_cursor: datetime):
        self.calls.append((slate_date, time_cursor))
        return (SECOND, FIRST, HIDDEN)


class Acks:
    def __init__(self) -> None:
        self.acknowledged: set[tuple[UUID, UUID]] = set()

    async def is_acknowledged(self, profile_id: UUID, game_id: UUID) -> bool:
        return (profile_id, game_id) in self.acknowledged

    async def acknowledge(self, profile_id: UUID, game_id: UUID) -> None:
        self.acknowledged.add((profile_id, game_id))


def field(name: GameFieldName, value: str | int | float, when: datetime = CURSOR):
    return GameField(name, value, when, when)


def snapshot(game_id: UUID, *, pregame: bool = True, future_score: bool = False):
    fields = (
        field(GameFieldName.HOME_TEAM, "Home"),
        field(GameFieldName.AWAY_TEAM, "Away"),
        field(GameFieldName.SCHEDULED_TIP, TIP.isoformat()),
    ) if pregame else (
        field(GameFieldName.HOME_TEAM, "Backfilled", FINAL),
        field(GameFieldName.AWAY_TEAM, "Backfilled", FINAL),
        field(GameFieldName.SCHEDULED_TIP, TIP.isoformat(), FINAL),
    )
    fields += (
        field(GameFieldName.HOME_SCORE, 123, FINAL),
        field(GameFieldName.AWAY_SCORE, 101, FINAL),
        field(GameFieldName.RESULT, "Home won", FINAL),
        field(GameFieldName.HIGHLIGHT_THUMBNAIL, "winning.jpg", FINAL),
        field(GameFieldName.HIGHLIGHT_RUNTIME_SECONDS, 1900, FINAL),
    )
    if future_score:
        fields += (field(GameFieldName.PREGAME_INTEREST, 9.9, FINAL),)
    return TrustedGameSnapshot(game_id, TIP, FINAL, fields, full_available=True)


class Games:
    async def get(self, game_id: UUID, *, time_cursor: datetime):
        if game_id == HIDDEN:
            return snapshot(game_id, pregame=False)
        return snapshot(game_id, future_score=True)


def setup():
    timeline, slates, acks = Clock(), Slate(), Acks()
    service = GameListService(timeline, slates, Games(), acks)
    return service, timeline, slates, acks


@pytest.mark.asyncio
async def test_known_pregame_games_only_and_no_hidden_field_or_order_leakage():
    service, timeline, slates, acks = setup()
    before = await service.list_games(PROFILE, slate_date=DAY)
    assert before.time_cursor == CURSOR
    assert slates.calls == [(DAY, CURSOR)]
    assert [c.game_id for c in before.games] == [FIRST, SECOND]  # stable UUID fallback
    for card in before.games:
        assert card.state == "sealed"
        wire = card.model_dump_json()
        assert "123" not in wire and "winning.jpg" not in wire
        assert "home_score" not in wire and "pregame_interest" not in wire
        assert "highlight_runtime_seconds" not in wire
    acks.acknowledged.add((PROFILE, SECOND))
    after = await service.list_games(PROFILE, slate_date=DAY)
    assert [c.game_id for c in after.games] == [FIRST, SECOND]
    assert [c.state for c in after.games] == ["sealed", "acknowledged"]
    assert timeline.cursor == CURSOR


@pytest.mark.asyncio
async def test_uninitialized_profile_is_not_automatically_created():
    service, _, slates, _ = setup()
    with pytest.raises(TimelineNotInitializedError):
        await service.list_games(OTHER, slate_date=DAY)
    assert slates.calls == []


def test_eastern_calendar_day_handles_midnight_and_daylight_saving():
    start, end = nba_day_bounds(DAY)
    assert start == datetime(2026, 10, 8, 4, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 9, 4, tzinfo=timezone.utc)
    spring_start, spring_end = nba_day_bounds(date(2026, 3, 8))
    fall_start, fall_end = nba_day_bounds(date(2026, 11, 1))
    assert spring_end - spring_start == timedelta(hours=23)
    assert fall_end - fall_start == timedelta(hours=25)


def test_http_surface_requires_date_and_known_initialized_profile():
    service, _, _, _ = setup()
    app.dependency_overrides[get_game_list_service] = lambda: service
    try:
        with TestClient(app) as client:
            uri = f"/profiles/{PROFILE}/games"
            assert client.get(uri).status_code == 422
            assert client.get(uri + "?date=2026-13-01").status_code == 422
            response = client.get(uri + "?date=2026-10-08")
            assert response.status_code == 200
            data = response.json()
            assert data["time_cursor"] == "2026-10-08T16:00:00Z"
            assert len(data["games"]) == 2
            assert set(data["games"][0]) == {
                "game_id", "state", "disclosure", "home_team", "away_team", "scheduled_tip",
            }
            assert client.get(f"/profiles/{OTHER}/games?date=2026-10-08").status_code == 404
    finally:
        app.dependency_overrides.clear()
