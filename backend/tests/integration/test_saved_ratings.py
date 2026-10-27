"""Durable published ratings: cold reads do no scoring; explicit updates append."""
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, text

from integration.test_morning_persistence import setup, NOW, evidence, FixtureCollector
from nba_time_machine.api.viewing_guide import router
from nba_time_machine.db import RecommendationScoreRecord, SportsExternalIdentityRecord
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository
from nba_time_machine.workbench.service import inspect_ratings, saved_evidence

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def capture(factory):
    day = date(2026, 5, 1) + timedelta(days=uuid4().int % 28)
    e = evidence()
    e = e.model_copy(update={'season': 'saved-' + str(uuid4()), 'ref': e.ref.model_copy(update={
        'day': day, 'scheduled_at': e.ref.scheduled_at + timedelta(days=(day-e.ref.day).days)})})
    await MorningStore(factory, manual=True).collect(FixtureCollector([e]), day)
    async with factory() as session:
        game = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == 'espn', SportsExternalIdentityRecord.entity_type == 'game',
            SportsExternalIdentityRecord.external_id == e.external_id))
    return day, game, e


async def test_fresh_admin_and_guide_read_same_saved_rating_without_deriving():
    engine, factory = await setup()
    try:
        day, game, evidence = await capture(factory)
        published = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=published, write=True)
        async with factory() as session:
            before = next(g for g in (await inspect_ratings(session, day, published))['games'] if g['game_id'] == str(game))
        assert before['enrichment']['players'] and before['metrics']
        # New source content is not a request to replace the saved calculation.
        corrected = evidence.model_copy(update={'observed_at': NOW + timedelta(hours=2), 'notes': ('new_revision',)})
        await MorningStore(factory, manual=True).collect(FixtureCollector([corrected]), day)
        queries = []
        def count(conn, cursor, statement, parameters, context, many):
            queries.append(statement)
        event.listen(engine.sync_engine, 'before_cursor_execute', count)
        try:
            with patch.object(MorningRankingPipeline, 'derive', side_effect=AssertionError('read recalculated')):
                # A new session represents a cold process with no memory cache.
                async with factory.begin() as session:
                    await session.execute(text('SET TRANSACTION READ ONLY'))
                    queries.clear()
                    after = next(g for g in (await inspect_ratings(session, day, NOW + timedelta(hours=3)))['games'] if g['game_id'] == str(game))
                    assert len(queries) <= 5
                    assert after == before
                    assert after['evidence'] is None
                    assert (await saved_evidence(session, game, published))['external_id'] == evidence.external_id
                profile, cursor = uuid4(), NOW - timedelta(days=1)
                async with factory() as session:
                    await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cursor)
                # No shared prepared-day cache: two independently constructed apps.
                for _ in range(2):
                    app = FastAPI()
                    app.state.session_factory = factory
                    app.include_router(router)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                        response = await client.post(f'/profiles/{profile}/guide/disclose', json={
                            'date': str(day), 'mode': 'browse', 'time_cursor': cursor.isoformat(),
                            'level': 'rating', 'game_id': str(game), 'consent': True})
                        assert response.status_code == 200
                        assert response.json()['details'][str(game)]['rating'] == before['rating']['score']
        finally:
            event.remove(engine.sync_engine, 'before_cursor_execute', count)
        # Explicit publication, not a read, makes the new evidence effective.
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=NOW + timedelta(hours=3), write=True)
        async with factory() as session:
            scores = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game).order_by(RecommendationScoreRecord.as_of))).all()
            assert len(scores) == 2
            current = next(g for g in (await inspect_ratings(session, day, NOW + timedelta(hours=3)))['games'] if g['game_id'] == str(game))
            assert current['calculated_at'] != before['calculated_at']
            assert current['provenance']['fact_id'] != before['provenance']['fact_id']
            assert next(g for g in (await inspect_ratings(session, day, published))['games'] if g['game_id'] == str(game)) == before
    finally:
        await engine.dispose()


async def test_older_rating_without_details_stays_readable_and_missing_rating_is_not_calculated():
    engine, factory = await setup()
    try:
        day, game, _ = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        with patch.object(MorningRankingPipeline, 'derive', side_effect=AssertionError('implicit calculation')):
            async with factory() as session:
                item = next(g for g in (await inspect_ratings(session, day, cursor))['games'] if g['game_id'] == str(game))
                assert item['rating'] is None
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
            # Represent an archive written before the nullable-details migration.
            row = await session.scalar(select(RecommendationScoreRecord).where(RecommendationScoreRecord.game_id == game))
            row.inspection = None
        with patch.object(MorningRankingPipeline, 'derive', side_effect=AssertionError('implicit backfill')):
            async with factory() as session:
                item = next(g for g in (await inspect_ratings(session, day, cursor))['games'] if g['game_id'] == str(game))
                assert item['rating'] and item['published']
                assert 'older rating' in item['diagnostics'][0]
                assert len(await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((game,), as_of=cursor)) == 1
                assert await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((game,), as_of=NOW) == ()
    finally:
        await engine.dispose()
