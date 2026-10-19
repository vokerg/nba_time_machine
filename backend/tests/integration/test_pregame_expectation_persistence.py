"""Synthetic captures in disposable PostgreSQL; no live source calls."""
from datetime import date, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from integration.test_morning_persistence import setup, FixtureCollector
from test_game_records import evidence_with_records, NOW, DAY
from nba_time_machine.db import SportsExternalIdentityRecord, SourceRecord, RecommendationScoreRecord
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.ranking.scoring import OVERALL_VERSION, FeatureObservation, PostgameSignal, score_postgame
from nba_time_machine.ranking.repository import SqlAlchemyRankingStore
from nba_time_machine.sports.morning_models import MatchupRecords, SeasonRecord
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.api.viewing_guide import router
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_open_reconstruction_shared_overall_archive_and_strict_isolation():
    engine, factory = await setup()
    e = evidence_with_records(str(uuid4().int)[:12])
    day = date(2026, 3, 4)
    e = e.model_copy(update={'ref':e.ref.model_copy(update={'day':day,
        'scheduled_at':e.ref.scheduled_at + timedelta(days=(day - e.ref.day).days)})})
    # Synthetic strong matchup: both teams entered 20–5; outcome is removed.
    home_after, away_after = SeasonRecord(wins=21, losses=5), SeasonRecord(wins=20, losses=6)
    e = e.model_copy(update={'records':MatchupRecords(home_after=home_after, away_after=away_after),
        'ref':e.ref.model_copy(update={'home_record':home_after, 'away_record':away_after})})
    cutoff = NOW + timedelta(hours=1)
    try:
        assert (await MorningStore(factory, manual=True).collect(FixtureCollector([e]), day)).captures_written == 1
        async with factory.begin() as session:
            gid = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key == 'espn',
                SportsExternalIdentityRecord.entity_type == 'game',
                SportsExternalIdentityRecord.external_id == e.external_id))
            pipeline = MorningRankingPipeline(session)
            public = await pipeline.expectations((gid,), as_of=cutoff)
            expectation = public[str(gid)]
            assert expectation['teams'][0]['wins'] == 20 and expectation['teams'][0]['losses'] == 5
            assert 'removed_result' not in str(public) and 'provider_after_wins' not in str(public)
            assert await pipeline.expectations((gid,), as_of=cutoff, strict=True) == {}
            assert await pipeline.expectations((gid,), as_of=NOW - timedelta(seconds=1)) == {}
            composite = (await pipeline.derive(gid, as_of=cutoff))[2]
            legacy = score_postgame(gid, {PostgameSignal(p.signal): FeatureObservation(
                p.normalized_value, p.source_ref, p.available_at, p.observed_at)
                for p in composite.components[:-1]}, final_at=NOW, as_of=cutoff)
            await SqlAlchemyRankingStore(session).archive(legacy)
            assert await pipeline.process(gid, as_of=cutoff, write=True)
            assert composite.value == round(min(10, legacy.value + expectation['overall_points']), 4)
            assert expectation['overall_points'] > 0
            profile = uuid4()
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cutoff)
        async with factory() as session:
            archived = await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,), as_of=cutoff)
            assert len(archived) == 1 and archived[0].model_version == OVERALL_VERSION
            assert archived[0].components[-1].weighted_contribution == expectation['overall_points']
            assert await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == gid))
        app = FastAPI()
        app.state.session_factory = factory
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = f'/profiles/{profile}/guide'
            response = await client.get(path, params={'date':str(day), 'mode':'browse'})
            assert response.status_code == 200, response.text
            body = response.json()
            assert str(gid) in body['expectations']
            assert all('home_score' not in g and 'rating' not in g for g in body['games'])
            strict = await client.get(path, params={'date':str(day), 'mode':'time-machine'})
            assert strict.status_code == 200 and strict.json()['expectations'] == {}
            rating = await client.post(path + '/disclose', json={'date':str(day), 'mode':'browse',
                'time_cursor':cutoff.isoformat(), 'consent':True, 'level':'rating', 'game_id':str(gid)})
            assert rating.status_code == 200, rating.text
            detail = rating.json()['details'][str(gid)]
            assert detail['model'] == OVERALL_VERSION
            assert any(p['label'] == 'Pregame matchup strength' for p in detail['components'])
        # Source revocation masks both the expectation and archived score.
        async with factory.begin() as session:
            source = await session.get(SourceRecord, 'espn-nba-games')
            source.verification_status = 'unverified'
        async with factory() as session:
            assert await MorningRankingPipeline(session).expectations((gid,), as_of=cutoff) == {}
            assert await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,), as_of=cutoff) == ()
        async with factory.begin() as session:
            source = await session.get(SourceRecord, 'espn-nba-games')
            source.verification_status = 'verified'
    finally:
        await engine.dispose()


async def test_bad_pbp_does_not_hide_independent_entering_records_and_revision_masks_old_context():
    engine, factory = await setup()
    e = evidence_with_records(str(uuid4().int)[:12]).model_copy(update={'pbp_errors':('missing_periods',)})
    day = date(2026, 3, 5)
    e = e.model_copy(update={'ref':e.ref.model_copy(update={'day':day,
        'scheduled_at':e.ref.scheduled_at + timedelta(days=(day - e.ref.day).days)})})
    try:
        await MorningStore(factory, manual=True).collect(FixtureCollector([e]), day)
        async with factory() as session:
            gid = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key == 'espn', SportsExternalIdentityRecord.entity_type == 'game',
                SportsExternalIdentityRecord.external_id == e.external_id))
            pipeline = MorningRankingPipeline(session)
            assert await pipeline.expectations((gid,), as_of=NOW + timedelta(hours=1))
            assert await pipeline.derive(gid, as_of=NOW + timedelta(hours=1)) is None
        revised = e.model_copy(update={'observed_at':NOW + timedelta(hours=2), 'records':None})
        await MorningStore(factory, manual=True).collect(FixtureCollector([revised]), day)
        async with factory() as session:
            assert await MorningRankingPipeline(session).expectations((gid,), as_of=NOW + timedelta(hours=3)) == {}
    finally:
        await engine.dispose()


async def test_entering_records_are_visible_before_scoring_minimum_and_withheld_in_strict_mode():
    from nba_time_machine.sports.morning_models import SeasonRecord, MatchupRecords
    engine,factory=await setup()
    day=date(2026,11,10)
    e=evidence_with_records(str(uuid4().int)[:12])
    after_home,after_away=SeasonRecord(wins=2,losses=0),SeasonRecord(wins=0,losses=2)
    observed=NOW+timedelta(days=30)
    e=e.model_copy(update={'season':'2026-2027','observed_at':observed,
        'records':MatchupRecords(home_after=after_home,away_after=after_away),
        'ref':e.ref.model_copy(update={'day':day,'scheduled_at':e.ref.scheduled_at+timedelta(days=(day-e.ref.day).days),
            'home_record':after_home,'away_record':after_away})})
    try:
        assert (await MorningStore(factory,manual=True).collect(FixtureCollector([e]),day)).captures_written==1
        async with factory() as session:
            gid=await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key=='espn',SportsExternalIdentityRecord.entity_type=='game',
                SportsExternalIdentityRecord.external_id==e.external_id))
            pipeline=MorningRankingPipeline(session)
            assert await pipeline.expectations((gid,),as_of=observed+timedelta(hours=1))=={}
            rows=pipeline.open_records[str(gid)]['teams']
            assert [(r['wins'],r['losses']) for r in rows]==[(1,0),(0,1)]
            assert all(set(r)=={'team','wins','losses'} for r in rows)
            await pipeline.expectations((gid,),as_of=observed+timedelta(hours=1),strict=True)
            assert pipeline.open_records=={}
    finally:await engine.dispose()
