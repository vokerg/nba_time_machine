"""Observed backfill membership is timestamp-gated, independent of outcomes."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.db import (DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord,
    SourceRecord, TeamRecord, create_database_engine, create_session_factory)
from nba_time_machine.api.game_list import game_list_response
from nba_time_machine.spoilers.game_list import GameListService, SqlAlchemyGameSlateRepository
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_known_only_after_observation_without_score_or_pregame_fabrication():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip('disposable DATABASE_URL not configured')
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    season, home, away, game, profile = [uuid4() for _ in range(5)]
    source = 'observed-' + str(uuid4())
    tip = datetime(2025, 10, 21, 23, tzinfo=timezone.utc)
    observed = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    try:
        async with factory.begin() as session:
            session.add_all([SeasonRecord(id=season, league='NBA', label=str(season)),
                TeamRecord(id=home, league='NBA', name='Home'), TeamRecord(id=away, league='NBA', name='Away'),
                SourceRecord(id=source, name='Fixture', kind='structured', adapter='fixture', category=[],
                             locator='fixture://observed', enabled=False, verification_status='verified',
                             cadence_minutes=60, requires_auth=False, retention_policy='metadata_only')])
            await session.flush()
            session.add(GameRecord(id=game, season_id=season, home_team_id=home, away_team_id=away))
            await session.flush()
            session.add(GameObservationRecord(game_id=game, source_id=source, observed_at=observed,
                available_at=observed, status='final', scheduled_tip_at=tip, home_score=100, away_score=90))
        async with factory() as session:
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            await timeline.initialize(profile, observed - timedelta(seconds=1))
        async def cards(observed_view):
            async with factory() as session:
                service = GameListService(TimelineService(SqlAlchemyTimelineRepository(session)),
                    SqlAlchemyGameSlateRepository(session, observed_schedule=observed_view),
                    SqlAlchemyGameSnapshotRepository(session, observed_schedule=observed_view),
                    SqlAlchemyGameAcknowledgementRepository(session), observed_schedule=observed_view)
                return [card.model_dump(mode='json') for card in game_list_response(
                    await service.list_games(profile, slate_date=date(2025, 10, 21))).games if card.game_id == game]
        assert await cards(True) == []
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).advance(profile, observed)
        assert await cards(False) == []
        result = await cards(True)
        assert len(result) == 1
        assert result[0]['home_team'] == 'Home'
        assert result[0]['scheduled_tip'] == tip.isoformat()
        assert 'home_score' not in result[0] and 'result' not in result[0]
        assert 'pregame_interest' not in result[0]
        # Status changes do not remove a known schedule from the observed view.
        async with factory.begin() as session:
            session.add(GameObservationRecord(game_id=game, source_id=source, observed_at=observed + timedelta(seconds=1),
                available_at=observed + timedelta(seconds=1), status='postponed', scheduled_tip_at=tip))
        assert await cards(True) == result  # later observation remains hidden
    finally:
        await engine.dispose()
