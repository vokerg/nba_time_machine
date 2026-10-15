"""Real PostgreSQL coverage/revision boundaries using synthetic histories only."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from integration.test_morning_persistence import setup, evidence, FixtureCollector, NOW
from test_game_context import full_history
from test_workbench import baseline
from nba_time_machine.db import CollectionRunRecord, RecommendationScoreRecord, SourceRecord, TemporalFactRecord, SportsExternalIdentityRecord
from nba_time_machine.ranking.context_reader import read_context
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.sports.history_collection import collect_and_store, persist_day
from nba_time_machine.sports.morning import PublicNBAClient
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.standings_history import FACT_TYPE, SOURCE_ID, START
from nba_time_machine.workbench.app import CANDIDATE_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig
from nba_time_machine.workbench.service import inspect_game

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_history_replay_asof_corrections_ties_revocation_and_readonly_proposal():
    from nba_time_machine.db import GameObservationRecord
    engine, factory = await setup()
    run_id = uuid4()
    history = full_history()
    target = START + timedelta(days=20)
    e = evidence()
    e = e.model_copy(update={'season':'2025-2026', 'game_type':'regular_season',
        'ref': e.ref.model_copy(update={'day':target, 'scheduled_at':datetime(2025,11,10,23,tzinfo=timezone.utc)})})
    v3 = TuningConfig.model_validate_json(CANDIDATE_CONFIG.with_name('entertainment-context-v3.json').read_text())
    try:
        async with factory.begin() as session:
            session.add(CollectionRunRecord(id=run_id, collector_version='synthetic-history-test', started_at=NOW))
            await session.flush()
            source = await session.get(SourceRecord, SOURCE_ID)
            # Missing one day cannot turn into an ordinary/zero-importance game.
            for day in history[:-1]:
                assert await persist_day(session, source, run_id, day, NOW)
        async with factory() as session:
            assert (await read_context(session, e, NOW + timedelta(hours=1)))['status'] == 'missing'
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_ID)
            assert await persist_day(session, source, run_id, history[-1], NOW)
            assert not await persist_day(session, source, run_id, history[-1], NOW + timedelta(minutes=1))
        async with factory() as session:
            assert (await read_context(session, e, NOW - timedelta(seconds=1)))['status'] == 'missing'
            context = await read_context(session, e, NOW + timedelta(hours=1))
            assert context['status'] == 'available' and context['games_used'] == 300
            assert context['home']['games_played'] == 20
            assert all(datetime.fromisoformat(p['observed_at']) == NOW for p in context['provenance'])
        report = await MorningStore(factory, manual=True).collect(FixtureCollector([e]), target)
        assert report.captures_written == 1
        async with factory.begin() as session:
            game = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key=='espn', SportsExternalIdentityRecord.entity_type=='game',
                SportsExternalIdentityRecord.external_id==e.external_id))
            assert await MorningRankingPipeline(session).process(game, as_of=NOW+timedelta(hours=1), write=True)
        async with factory.begin() as session:
            from sqlalchemy import text
            await session.execute(text('SET TRANSACTION READ ONLY'))
            observation = await session.scalar(select(GameObservationRecord).where(GameObservationRecord.game_id==game))
            item = await inspect_game(session, observation, NOW+timedelta(hours=1), baseline(), v3)
            assert item['context']['included_in_proposal']
            assert item['experiment']['context_bonus'] > 0
            assert item['experiment']['coverage'] == 'complete'
            assert item['archived']['eligible']
            assert item['archived']['score'] == item['baseline']['score']
        from nba_time_machine.workbench.app import app
        app.state.session_factory = factory
        app.state.baseline = baseline()
        app.state.candidate = v3
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1234)), base_url='http://127.0.0.1:8765') as client:
            response = await client.get('/api/slate', params={'date':str(target), 'as_of':(NOW+timedelta(hours=1)).isoformat()})
            assert response.status_code == 200
            item = next(g for g in response.json()['games'] if g['game_id']==str(game))
            assert item['context']['games_used']==300 and item['experiment']['context_bonus'] > 0
            legacy = await client.post('/api/preview', json={'slate_date':str(target), 'as_of':(NOW+timedelta(hours=1)).isoformat(),
                'config':baseline().model_dump(exclude_none=True)})
            assert legacy.status_code==200
            item = next(g for g in legacy.json()['games'] if g['game_id']==str(game))
            assert 'context_bonus' not in item['experiment'] and not item['context']['included_in_proposal']
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id==game)) == 1
        # Newer invalid, expired, malformed and ambiguous revisions mask good history.
        for offset, fault in enumerate(('partial', 'expired', 'malformed', 'ambiguous'), 2):
            at = NOW + timedelta(hours=offset)
            async with factory.begin() as session:
                original = await session.scalar(select(TemporalFactRecord).where(
                    TemporalFactRecord.fact_type==FACT_TYPE,
                    TemporalFactRecord.fact_metadata['day'].astext==str(START)).order_by(TemporalFactRecord.observed_at).limit(1))
                value = dict(original.value)
                if fault == 'partial': value['errors']=['synthetic_failed_day']
                if fault == 'malformed': value={'broken': True}
                for _ in range(2 if fault == 'ambiguous' else 1):
                    session.add(TemporalFactRecord(subject_type='season', season_id=original.season_id,
                        source_id=SOURCE_ID, fact_type=FACT_TYPE, value=value,
                        observed_at=at, available_at=at, valid_from=at,
                        valid_to=at+timedelta(minutes=1) if fault=='expired' else None,
                        fact_metadata={'day':str(START)}))
            async with factory() as session:
                assert (await read_context(session, e, at+timedelta(minutes=2)))['status']=='missing'
                assert (await read_context(session, e, NOW+timedelta(hours=1)))['status']=='available'
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_ID)
            source.verification_status='unverified'
        async with factory() as session:
            assert 'not approved' in (await read_context(session, e, NOW+timedelta(hours=1)))['reason']
    finally:
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_ID)
            source.verification_status='verified'
        await engine.dispose()


async def test_inflight_source_policy_change_rejects_history_capture():
    from history_fixtures import scoreboard
    engine, factory = await setup()
    async def handle(request):
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_ID)
            source.verification_status='unverified'
        return httpx.Response(200, json=scoreboard(START))
    try:
        async with factory() as session:
            before = await session.scalar(select(func.count()).select_from(TemporalFactRecord).where(TemporalFactRecord.fact_type==FACT_TYPE))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            result = await collect_and_store(factory, PublicNBAClient(http, interval=0), START, START, manual=True)
        assert result.captures_written==0 and result.persistence_errors==1
        async with factory() as session:
            assert before == await session.scalar(select(func.count()).select_from(TemporalFactRecord).where(TemporalFactRecord.fact_type==FACT_TYPE))
    finally:
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_ID)
            source.verification_status='verified'
        await engine.dispose()
