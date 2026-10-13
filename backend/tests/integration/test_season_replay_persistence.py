"""Retrospective schedules stay separate from historical pregame truth."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from nba_time_machine.db import (DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord,
    SourceRecord, TeamRecord, create_database_engine, create_session_factory)
from nba_time_machine.api.game_list import game_list_response
from nba_time_machine.spoilers.game_list import GameListService, SqlAlchemyGameSlateRepository
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.spoilers.service import GameDisclosureService, SealedGameError
from nba_time_machine.spoilers.policy import DisclosureLayer
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replay_at_original_day_reveal_isolation_and_latest_schedule_correction():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip('disposable DATABASE_URL not configured')
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    season, home, away, game, profile = [uuid4() for _ in range(5)]
    source = 'replay-' + str(uuid4())
    tip = datetime(2025, 11, 3, 23, tzinfo=timezone.utc)
    cursor = tip - timedelta(hours=8)
    observed = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    try:
        async with factory.begin() as session:
            session.add_all([SeasonRecord(id=season, league='NBA', label=str(season)),
                TeamRecord(id=home, league='NBA', name='Home'), TeamRecord(id=away, league='NBA', name='Away'),
                SourceRecord(id=source, name='Fixture', kind='structured', adapter='fixture', category=[],
                    locator='fixture://replay', enabled=False, verification_status='verified',
                    cadence_minutes=60, requires_auth=False, retention_policy='metadata_only')])
            await session.flush()
            session.add(GameRecord(id=game, season_id=season, home_team_id=home, away_team_id=away))
            await session.flush()
            session.add(GameObservationRecord(game_id=game, source_id=source, observed_at=observed,
                available_at=observed, status='final', scheduled_tip_at=tip, home_score=100, away_score=90))
        async with factory() as session:
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            await timeline.initialize(profile, cursor)

        async def cards(day, *, replay=False, observed_view=False):
            async with factory() as session:
                service = GameListService(TimelineService(SqlAlchemyTimelineRepository(session)),
                    SqlAlchemyGameSlateRepository(session, season_replay=replay, observed_schedule=observed_view),
                    SqlAlchemyGameSnapshotRepository(session, season_replay=replay, observed_schedule=observed_view),
                    SqlAlchemyGameAcknowledgementRepository(session), season_replay=replay, observed_schedule=observed_view)
                return [card.model_dump(mode='json', exclude_none=True) for card in game_list_response(
                    await service.list_games(profile, slate_date=day)).games if card.game_id == game]

        day = date(2025, 11, 3)
        assert await cards(day) == []
        assert await cards(day, observed_view=True) == []
        before = await cards(day, replay=True)
        assert len(before) == 1
        assert before[0]['state'] == 'sealed'
        assert before[0]['scheduled_tip'] == tip.isoformat()
        assert set(before[0]) == {'game_id', 'state', 'disclosure', 'home_team', 'away_team', 'scheduled_tip'}
        assert await cards(day + timedelta(days=1), replay=True) == []
        async with factory() as session:
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            disclosure = GameDisclosureService(timeline, SqlAlchemyGameSnapshotRepository(session),
                SqlAlchemyGameAcknowledgementRepository(session))
            with pytest.raises(SealedGameError):
                await disclosure.disclose(profile, game, DisclosureLayer.FULL)
            result = await disclosure.reveal_full(profile, game)
            assert result.projection.fields['home_score'] == 100
            assert (await timeline.resume(profile)).time_cursor == cursor
            observation = await session.get(GameObservationRecord, (await session.scalar(
                select(GameObservationRecord.id).where(GameObservationRecord.game_id == game))))
            assert observation.available_at == observed and observation.observed_at == observed
        after = await cards(day, replay=True)
        assert after == [{**before[0], 'state': 'acknowledged'}]
        # A later schedule revision moves membership, without consulting its status.
        async with factory.begin() as session:
            session.add(GameObservationRecord(game_id=game, source_id=source,
                observed_at=observed + timedelta(seconds=1), available_at=observed + timedelta(seconds=1),
                status='postponed', scheduled_tip_at=tip - timedelta(days=1)))
        assert await cards(day, replay=True) == []
        assert len(await cards(day - timedelta(days=1), replay=True)) == 1
    finally:
        await engine.dispose()
