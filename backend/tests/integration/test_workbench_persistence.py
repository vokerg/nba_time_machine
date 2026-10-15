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
