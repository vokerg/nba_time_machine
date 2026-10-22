"""Synthetic pre-tip star snapshots, roster provenance and independent coverage."""
from datetime import datetime, date, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from integration.test_morning_persistence import setup, FixtureCollector, evidence
from test_star_power import ranking, catalog, evidence as player_evidence
from nba_time_machine.db import SourceRecord, TemporalFactRecord, SportsExternalIdentityRecord, GameRecord, GameObservationRecord
from nba_time_machine.ranking.player_rankings import SOURCE_ID, SOURCE_URL
from nba_time_machine.ranking.player_ranking_store import import_snapshot
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.ranking.scoring import STAR_OVERALL_VERSION
from nba_time_machine.ranking.pregame import PregameExpectation
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.player_identities import FACT_TYPE as ROSTER_TYPE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
TIP = datetime(2026,10,16,23,tzinfo=timezone.utc)
KNOWN = TIP - timedelta(hours=12)
CUTOFF = TIP + timedelta(days=1)


async def seed(factory, monkeypatch):
    import nba_time_machine.ranking.player_ranking_store as store
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):return KNOWN
    async def fake_catalog(*args):return catalog()
    monkeypatch.setattr(store,'identity_catalog',fake_catalog)
    monkeypatch.setattr(store,'datetime',FixedDatetime)
    async with factory.begin() as session:
        source = await session.get(SourceRecord,SOURCE_ID)
        if source is None:
            source=SourceRecord(id=SOURCE_ID,name='Synthetic only',kind='structured',adapter='manual_player_rankings',
                locator=SOURCE_URL,enabled=False,verification_status='verified',cadence_minutes=20160,
                requires_auth=False,retention_policy='normalized_full',adapter_settings={})
            session.add(source)
        source.verification_status='verified';source.adapter='manual_player_rankings';source.retention_policy='normalized_full'
        source.adapter_settings={'permission_reference':'synthetic-test-only','automated_access':False}
    async with factory.begin() as session:
        await import_snapshot(session,ranking().model_copy(update={'ranking_version':'pregame-'+str(uuid4())}),write=True)
    e=evidence()
    e=e.model_copy(update={'observed_at':CUTOFF,'game_type':'preseason','season':'2026-2027',
        'ref':e.ref.model_copy(update={'scheduled_at':TIP,'day':TIP.date(),'season_type':1})})
    players=tuple(p.model_copy(update={'team_id':e.home.external_id if p.team_id=='1' else e.away.external_id,
        'statistics':{'PTS':4 if p.external_id=='1' else 3 if p.external_id=='2' else 0}})
        for p in player_evidence().players)
    e=e.model_copy(update={'players':players,'box_errors':(),'box_team_errors':{}})
    assert (await MorningStore(factory,manual=True).collect(FixtureCollector([e]),TIP.date())).captures_written==1
    async with factory.begin() as session:
        gid=await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key=='espn',SportsExternalIdentityRecord.entity_type=='game',
            SportsExternalIdentityRecord.external_id==e.external_id))
        game=await session.get(GameRecord,gid)
        session.add(GameObservationRecord(game_id=gid,source_id='espn-nba-games',observed_at=KNOWN,
            available_at=KNOWN,status='scheduled',scheduled_tip_at=TIP))
        rosters=[]
        for tid,team,ids in [(game.home_team_id,e.home,[1,3,5,901]),(game.away_team_id,e.away,[2,4,6,8,902])]:
            fact=TemporalFactRecord(subject_type='team',team_id=tid,source_id='espn-nba-games',fact_type=ROSTER_TYPE,
                value={'team':team.abbreviation,'team_id':team.external_id,'players':[
                    {'espn_id':str(i),'name':f'Fixture Player {i}','team':team.abbreviation} for i in ids]},
                valid_from=KNOWN,observed_at=KNOWN,available_at=KNOWN,fact_metadata={'identity_only':True,'not_game_participation':True})
            session.add(fact);rosters.append(fact)
        await session.flush()
        roster_ids=[f.id for f in rosters]
    return gid,e,roster_ids


async def test_preseason_stars_without_records_are_open_and_pre_tip_bounded(monkeypatch):
    engine,factory=await setup()
    try:
        gid,e,rosters=await seed(factory,monkeypatch)
        async with factory() as session:
            pipeline=MorningRankingPipeline(session)
            value=(await pipeline.expectations((gid,),as_of=CUTOFF))[str(gid)]
            assert value['coverage']=='stars-only' and value['basis']=='known-pre-tip' and value['rating']>0
            assert value['star_power']['teams'][0]['players'][0]['rank']==1
            assert len(value['star_power']['teams'][1]['players']) == 3
            assert [p['name'] for p in value['star_power']['teams'][1]['ranked_players']] == [
                'Fixture Player 2', 'Fixture Player 4', 'Fixture Player 6', 'Fixture Player 8']
            assert value['star_power']['teams'][0]['unranked_players']==['Fixture Player 901']
            assert value['star_power']['teams'][1]['unranked_players']==['Fixture Player 902']
            assert 'Fixture Player 8' not in value['star_power']['teams'][1]['unranked_players']
            assert all('wins' not in t for t in value['teams'])
            PregameExpectation.model_validate(value)
            strict=(await pipeline.expectations((gid,),as_of=KNOWN+timedelta(hours=1),strict=True))[str(gid)]
            assert strict['basis']=='known-pre-tip' and strict['rating']==value['rating']
            assert await pipeline.expectations((gid,),as_of=KNOWN-timedelta(seconds=1),strict=True)=={}
            derived=await pipeline.derive(gid,as_of=CUTOFF)
            assert derived is not None and derived[2].model_version==STAR_OVERALL_VERSION
            assert derived[2].components[-1].signal=='star_power'
            # The same reader rejects not-yet-known ranking/roster inputs.
            from nba_time_machine.ranking.pregame_stars import PregameStarReader
            from nba_time_machine.db import SeasonRecord
            game=await session.get(GameRecord,gid);season=await session.get(SeasonRecord,game.season_id)
            sources={key:await session.get(SourceRecord,key) for key in (SOURCE_ID,'espn-nba-games')}
            early=PregameStarReader(session,{gid:(game,season.label)},sources,KNOWN-timedelta(seconds=1),latest_tip=TIP)
            await early.load()
            assert (await early.read(gid,TIP))['potential'] is None
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(gid,as_of=CUTOFF,write=True)
        from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
        async with factory() as session:
            assert (await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,),as_of=CUTOFF))[0].model_version==STAR_OVERALL_VERSION
        # Permission revocation masks both open potential and the realized archive.
        async with factory.begin() as session:
            source=await session.get(SourceRecord,SOURCE_ID)
            source.verification_status='unverified'
        async with factory() as session:
            assert await MorningRankingPipeline(session).expectations((gid,),as_of=CUTOFF)=={}
            assert await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,),as_of=CUTOFF)==()
        async with factory.begin() as session:
            source=await session.get(SourceRecord,SOURCE_ID)
            source.verification_status='verified'
        from nba_time_machine.spoilers.guide_cache import guide_revision
        async with factory() as session:
            before=await guide_revision(session,CUTOFF)
        # Revoked or ambiguous newest roster must not fall back to an older clean row.
        async with factory.begin() as session:
            original=await session.get(TemporalFactRecord,rosters[0])
            session.add(TemporalFactRecord(subject_type='team',team_id=original.team_id,source_id=original.source_id,
                fact_type=ROSTER_TYPE,value={'invalid':'latest roster'},valid_from=KNOWN+timedelta(hours=1),
                observed_at=KNOWN+timedelta(hours=1),available_at=KNOWN+timedelta(hours=1),fact_metadata={'identity_only':True,'not_game_participation':True}))
        async with factory() as session:
            assert await MorningRankingPipeline(session).expectations((gid,),as_of=CUTOFF)=={}
            assert await guide_revision(session,CUTOFF)!=before
    finally:await engine.dispose()
