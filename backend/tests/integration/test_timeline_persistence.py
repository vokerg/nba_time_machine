from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.db import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from nba_time_machine.temporal import (
    SqlAlchemyTimelineRepository,
    TimelineService,
    TimelineWouldMoveBackwardError,
)


def _database_settings_or_skip() -> DatabaseSettings:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_timeline_survives_new_session_and_never_regresses() -> None:
    engine = create_database_engine(_database_settings_or_skip())
    session_factory = create_session_factory(engine)
    profile_id = uuid4()
    initial_cursor = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    later_cursor = initial_cursor + timedelta(hours=2)

    try:
        async with session_factory() as session:
            first_service = TimelineService(SqlAlchemyTimelineRepository(session))
            initialized = await first_service.initialize(profile_id, initial_cursor)
            assert initialized.time_cursor == initial_cursor

        async with session_factory() as session:
            restarted_service = TimelineService(SqlAlchemyTimelineRepository(session))
            resumed = await restarted_service.resume(profile_id)
            assert resumed.time_cursor == initial_cursor

            advanced = await restarted_service.advance(profile_id, later_cursor)
            assert advanced.time_cursor == later_cursor

        async with session_factory() as session:
            later_service = TimelineService(SqlAlchemyTimelineRepository(session))
            with pytest.raises(TimelineWouldMoveBackwardError):
                await later_service.advance(
                    profile_id,
                    initial_cursor + timedelta(minutes=30),
                )

            final_state = await later_service.resume(profile_id)
            assert final_state.time_cursor == later_cursor
    finally:
        await engine.dispose()
