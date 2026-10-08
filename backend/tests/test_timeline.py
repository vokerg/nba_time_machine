from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from nba_time_machine.api.timeline import get_timeline_service
from nba_time_machine.main import app
from nba_time_machine.temporal import (
    TimelineService,
    TimelineState,
    TimelineTimestampError,
    TimelineWouldMoveBackwardError,
)


class InMemoryTimelineRepository:
    def __init__(self) -> None:
        self.states: dict[UUID, TimelineState] = {}

    async def get(self, profile_id: UUID) -> TimelineState | None:
        return self.states.get(profile_id)

    async def initialize(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState | None:
        if profile_id in self.states:
            return None
        state = TimelineState(
            profile_id=profile_id,
            time_cursor=time_cursor,
            initialized_at=time_cursor,
            updated_at=time_cursor,
        )
        self.states[profile_id] = state
        return state

    async def advance_if_not_backward(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState | None:
        current = self.states.get(profile_id)
        if current is None or time_cursor < current.time_cursor:
            return None
        state = TimelineState(
            profile_id=profile_id,
            time_cursor=time_cursor,
            initialized_at=current.initialized_at,
            updated_at=time_cursor,
        )
        self.states[profile_id] = state
        return state


@pytest.mark.asyncio
async def test_timeline_normalizes_timezone_and_rejects_backward_movement() -> None:
    profile_id = uuid4()
    repository = InMemoryTimelineRepository()
    service = TimelineService(repository)

    initialized = await service.initialize(
        profile_id,
        datetime(2026, 10, 8, 12, 0, tzinfo=timezone(timedelta(hours=4))),
    )

    assert initialized.time_cursor == datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    assert await service.resume(profile_id) == initialized

    same = await service.advance(profile_id, initialized.time_cursor)
    assert same.time_cursor == initialized.time_cursor

    advanced = await service.advance(
        profile_id,
        datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert advanced.time_cursor == datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

    with pytest.raises(TimelineWouldMoveBackwardError):
        await service.advance(
            profile_id,
            datetime(2026, 10, 8, 8, 59, 59, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_timeline_rejects_naive_timestamp() -> None:
    service = TimelineService(InMemoryTimelineRepository())

    with pytest.raises(TimelineTimestampError):
        await service.initialize(uuid4(), datetime(2026, 10, 8, 8, 0))


@pytest.mark.asyncio
async def test_game_boundary_is_inclusive_and_has_no_side_effect() -> None:
    profile_id = uuid4()
    cursor = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    state = TimelineState(
        profile_id=profile_id,
        time_cursor=cursor,
        initialized_at=cursor,
        updated_at=cursor,
    )

    assert TimelineService.has_advanced_past_game(
        state,
        protection_ends_at=cursor,
    )
    assert not TimelineService.has_advanced_past_game(
        state,
        protection_ends_at=cursor + timedelta(microseconds=1),
    )


def test_timeline_api_contract_and_backward_conflict() -> None:
    profile_id = uuid4()
    service = TimelineService(InMemoryTimelineRepository())
    app.dependency_overrides[get_timeline_service] = lambda: service

    try:
        with TestClient(app) as client:
            initialized = client.post(
                f"/timeline/{profile_id}",
                json={"time_cursor": "2026-10-08T12:00:00+04:00"},
            )
            assert initialized.status_code == 201
            assert initialized.json()["profile_id"] == str(profile_id)
            assert initialized.json()["time_cursor"] == "2026-10-08T08:00:00Z"

            resumed = client.get(f"/timeline/{profile_id}")
            assert resumed.status_code == 200
            assert resumed.json()["time_cursor"] == "2026-10-08T08:00:00Z"

            advanced = client.put(
                f"/timeline/{profile_id}",
                json={"time_cursor": "2026-10-08T08:30:00Z"},
            )
            assert advanced.status_code == 200

            backward = client.put(
                f"/timeline/{profile_id}",
                json={"time_cursor": "2026-10-08T08:29:59Z"},
            )
            assert backward.status_code == 409

            naive = client.put(
                f"/timeline/{profile_id}",
                json={"time_cursor": "2026-10-08T09:00:00"},
            )
            assert naive.status_code == 422
    finally:
        app.dependency_overrides.clear()
