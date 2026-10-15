"""Read-only PostgreSQL inspection; canonical source data stays untouched."""
from datetime import timedelta
import pytest
from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from integration.test_morning_persistence import setup, NOW, DAY
from integration.test_morning_ranking_pipeline import capture
from nba_time_machine.db import RecommendationScoreRecord, TemporalFactRecord
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.workbench.app import app, read_session
from nba_time_machine.workbench.service import inspect_slate
from test_workbench import baseline

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_candidate_inspection_cannot_change_queue_media_or_disclosure():
    """Combined #86/#88/#92/#93 contract: tuning grants no consumer permissions."""
    import httpx
    from uuid import uuid4
    from fastapi import FastAPI
    from nba_time_machine.api.watch_queue import router as queue_router
    from nba_time_machine.api.media_feed import router as media_router
    from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
    from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository
    from test_entertainment_features import candidate

    engine, factory = await setup()
    profile = uuid4()
    consumer = FastAPI()
    consumer.state.session_factory = factory
    consumer.include_router(queue_router)
    consumer.include_router(media_router)
    try:
        game, _ = await capture(factory)
        # The consumer remains before collection; the operator inspects later data.
        cursor = NOW - timedelta(minutes=1)
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cursor)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=NOW + timedelta(hours=1), write=True)
        base = f'/profiles/{profile}'
        params = {'time_cursor': cursor.isoformat()}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=consumer), base_url='http://test') as client:
            assert (await client.put(f'{base}/watch-queue/{game}', json={
                **params, 'queue_state': 'done'})).status_code == 204
            queue_before = await client.get(f'{base}/watch-queue', params=params)
            media_before = await client.get(f'{base}/media', params=params)
            assert queue_before.status_code == media_before.status_code == 200
            card = queue_before.json()['items'][0]['game']
            assert card is not None and card['state'] == 'sealed'
            for forbidden in ('watchability', 'score', 'winner', 'runtime'):
                assert forbidden not in str(queue_before.json())
            assert media_before.json()['items'] == []
            async with factory.begin() as session:
                await session.execute(text('SET TRANSACTION READ ONLY'))
                report = await inspect_slate(session, DAY, NOW + timedelta(hours=1), baseline(), candidate())
                item = next(g for g in report['games'] if g['game_id'] == str(game))
                assert item['experiment']['score'] > item['archived']['score']
            assert (await client.get(f'{base}/watch-queue', params=params)).json() == queue_before.json()
            assert (await client.get(f'{base}/media', params=params)).json() == media_before.json()
        async with factory() as session:
            assert (await TimelineService(SqlAlchemyTimelineRepository(session)).resume(profile)).time_cursor == cursor
            assert not await SqlAlchemyGameAcknowledgementRepository(session).is_acknowledged(profile, game)
    finally:
        await engine.dispose()


async def test_readonly_transaction_rejects_writes_at_database_boundary():
    engine, factory = await setup()
    app.state.session_factory = factory
    dependency = read_session(Request({'type': 'http', 'app': app}))
    try:
        session = await anext(dependency)
        assert await session.scalar(text('SHOW transaction_read_only')) == 'on'
        assert await session.scalar(text('SHOW transaction_isolation')) == 'repeatable read'
        with pytest.raises(DBAPIError):
            await session.execute(text("INSERT INTO teams (id, league, name) VALUES (gen_random_uuid(), 'NBA', 'forbidden-workbench-write')"))
    finally:
        await dependency.aclose()
        await engine.dispose()


async def test_inspection_explains_archive_and_preview_without_mutating_facts():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
        async with factory() as session:
            facts_before = await session.scalar(select(func.count()).select_from(TemporalFactRecord))
            scores_before = await session.scalar(select(func.count()).select_from(RecommendationScoreRecord))
        config = baseline()
        experiment = config.model_copy(update={'version': 'experiment', 'weights': {
            'clutch': 0, 'lead_changes': 15, 'comeback': 20, 'overtime': 10}})
        async with factory.begin() as session:
            await session.execute(text('SET TRANSACTION READ ONLY'))
            report = await inspect_slate(session, DAY, cursor, config, experiment)
            item = next(g for g in report['games'] if g['game_id'] == str(game))
            assert item['archived']['eligible']
            assert item['archived']['score'] == item['baseline']['score']
            assert item['experiment']['score'] == 0
            assert item['provenance']['source_id'] == 'espn-nba-games'
            assert item['evidence']['external_id'] == e.external_id
            assert item['supporting_plays']
        async with factory() as session:
            assert facts_before == await session.scalar(select(func.count()).select_from(TemporalFactRecord))
            assert scores_before == await session.scalar(select(func.count()).select_from(RecommendationScoreRecord))
    finally:
        await engine.dispose()


async def test_partial_evidence_explains_why_preview_is_withheld():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game,
                TemporalFactRecord.fact_type == 'provider_game_evidence'))
            fact.value = {**fact.value, 'pbp_errors': ['score_regression']}
        async with factory.begin() as session:
            await session.execute(text('SET TRANSACTION READ ONLY'))
            report = await inspect_slate(session, DAY, cursor, baseline(), baseline())
            item = next(g for g in report['games'] if g['game_id'] == str(game))
            assert item['baseline'] is item['experiment'] is None
            assert 'score_regression' in item['diagnostics']
            assert item['evidence']['plays'] and not item['supporting_plays']
    finally:
        await engine.dispose()


async def test_v2_http_preview_is_default_and_preserves_archived_scores():
    import httpx
    from test_entertainment_features import candidate
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
        app.state.session_factory = factory
        app.state.baseline = baseline()
        app.state.candidate = candidate()
        async with factory() as session:
            before = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game))).all()
            original_value = before[0].score_value
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1234)),
                                     base_url='http://127.0.0.1:8765') as client:
            response = await client.get('/api/slate', params={'date': DAY.isoformat(), 'as_of': cursor.isoformat()})
            assert response.status_code == 200
            report = response.json()
            assert report['experiment_config']['schema_version'] == 2
            item = next(g for g in report['games'] if g['game_id'] == str(game))
            assert item['experiment']['score'] > item['baseline']['score']
            assert item['experiment']['drama_score'] == item['archived']['score']
            assert item['enrichment']['candidate_eligible']
            assert item['enrichment']['players'] and len(item['enrichment']['patterns']) == 6
            assert all(p['box_reference'].startswith('espn:') for p in item['enrichment']['players'])
            legacy = await client.post('/api/preview', json={'slate_date': DAY.isoformat(), 'as_of':cursor.isoformat(),
                                                            'config':baseline().model_dump(exclude_none=True)})
            assert legacy.status_code == 200
            old = next(g for g in legacy.json()['games'] if g['game_id'] == str(game))
            assert old['experiment']['score'] == old['archived']['score']
            assert 'player_bonus' not in old['experiment']
        async with factory() as session:
            after = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game))).all()
            assert len(after) == 1 and after[0].score_value == original_value
    finally:
        await engine.dispose()


@pytest.mark.parametrize('family', ['box', 'pbp'])
async def test_v2_family_coverage_is_explicit(family):
    from test_entertainment_features import candidate
    from nba_time_machine.workbench.service import inspect_game
    from nba_time_machine.db import GameObservationRecord
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game, TemporalFactRecord.fact_type == 'provider_game_evidence'))
            fact.value = {**fact.value, **({'players': []} if family == 'box' else {'pbp_errors': ['score_regression']})}
        async with factory.begin() as session:
            await session.execute(text('SET TRANSACTION READ ONLY'))
            observation = await session.scalar(select(GameObservationRecord).where(GameObservationRecord.game_id == game))
            item = await inspect_game(session, observation, cursor, baseline(), candidate())
            if family == 'box':
                assert item['experiment']['coverage'] == 'partial'
                assert item['experiment']['player_bonus'] is None
                assert item['enrichment']['players'] is None
                assert item['enrichment']['patterns']
            else:
                assert item['experiment'] is None
                assert item['enrichment']['players']
                assert item['enrichment']['patterns'] is None
                assert not item['enrichment']['candidate_eligible']
    finally:
        await engine.dispose()
