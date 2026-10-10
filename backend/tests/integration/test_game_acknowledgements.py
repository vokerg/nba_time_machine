"""PostgreSQL coverage for issue #14: identity, idempotency and final-state proof."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord,
    SourceRecord, TeamRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.policy import DisclosureLayer
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.spoilers.service import GameDisclosureService
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService

CURSOR = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
TIP = CURSOR + timedelta(hours=12)
FINAL = TIP + timedelta(hours=3)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_acknowledgement_persists_across_sessions_and_does_not_advance_timeline() -> None:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    profile, other = uuid4(), uuid4()
    game_id, season_id, home_id, away_id = uuid4(), uuid4(), uuid4(), uuid4()
    source_id = f"ack-test-{uuid4()}"

    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season_id, league="NBA", label="test-ack"),
                TeamRecord(id=home_id, league="NBA", name="Home"),
                TeamRecord(id=away_id, league="NBA", name="Away"),
                SourceRecord(
                    id=source_id, name="Acknowledgement fixture", kind="sports",
                    adapter="fixture", category=[], locator="fixture://nba",
                    enabled=False, verification_status="verified",
                    cadence_minutes=60, requires_auth=False,
                    retention_policy="metadata_only",
                ),
            ])
            await session.flush()
            session.add(GameRecord(
                id=game_id, season_id=season_id,
                home_team_id=home_id, away_team_id=away_id,
            ))
            await session.flush()
            session.add_all([
                GameObservationRecord(
                    game_id=game_id, source_id=source_id,
                    observed_at=CURSOR, available_at=CURSOR, status="scheduled",
                    scheduled_tip_at=TIP,
                ),
                GameObservationRecord(
                    game_id=game_id, source_id=source_id,
                    observed_at=FINAL, available_at=FINAL, status="final",
                    scheduled_tip_at=TIP, final_at=FINAL,
                    home_score=111, away_score=109,
                ),
            ])
            await session.commit()

        async with factory() as session:
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            await timeline.initialize(profile, CURSOR)
            await timeline.initialize(other, CURSOR)

        async with factory() as session:
            service = GameDisclosureService(
                TimelineService(SqlAlchemyTimelineRepository(session)),
                SqlAlchemyGameSnapshotRepository(session),
                SqlAlchemyGameAcknowledgementRepository(session),
            )
            before = await service.disclose(profile, game_id, DisclosureLayer.PREGAME)
            assert before.state == "sealed"
            assert before.projection.fields["home_team"] == "Home"
            assert "home_score" not in before.projection.fields
            assert (await service.reveal_full(profile, game_id)).projection.fields["home_score"] == 111
            assert (await service.reveal_full(profile, game_id)).state == "acknowledged"

        async with factory() as session:
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            assert (await timeline.resume(profile)).time_cursor == CURSOR
            repo = SqlAlchemyGameAcknowledgementRepository(session)
            assert await repo.is_acknowledged(profile, game_id)
            assert not await repo.is_acknowledged(other, game_id)
            service = GameDisclosureService(
                timeline,
                SqlAlchemyGameSnapshotRepository(session), repo,
            )
            assert (await service.disclose(profile, game_id, DisclosureLayer.FULL)).projection.fields["away_score"] == 109
            assert (await service.disclose(other, game_id, DisclosureLayer.PREGAME)).state == "sealed"

            await timeline.advance(other, FINAL)
            state = await service.disclose(other, game_id, DisclosureLayer.PREGAME)
            assert state.state == "acknowledged"
            assert not await repo.is_acknowledged(other, game_id)
    finally:
        await engine.dispose()
