"""Explicit retrospective tuning; no source timestamp or archived-score mutation."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from integration.test_morning_persistence import setup
from integration.test_star_snapshot_persistence import counts
from test_star_power import ranking,catalog,evidence
from nba_time_machine.db import SourceRecord,TemporalFactRecord
from nba_time_machine.ranking import player_ranking_store as store
from nba_time_machine.ranking.player_rankings import SOURCE_ID,SOURCE_URL,FACT_TYPE

pytestmark=[pytest.mark.integration,pytest.mark.asyncio]

async def test_first_backfill_latest_pre_tip_cross_season_and_asof(monkeypatch):
    engine,factory=await setup()
    async with factory() as session:
        earliest=await session.scalar(select(func.min(TemporalFactRecord.observed_at)).where(TemporalFactRecord.fact_type==FACT_TYPE))
    first_time=min(datetime(2026,10,1,12,tzinfo=timezone.utc), earliest-timedelta(days=4) if earliest else datetime(2026,10,1,12,tzinfo=timezone.utc))
    time=[first_time]
    class Clock(datetime):
        @classmethod
        def now(cls,*args):return time[0]
    monkeypatch.setattr(store,'datetime',Clock)
    async def fake_catalog(*args):return catalog()
    monkeypatch.setattr(store,'identity_catalog',fake_catalog)
    first=ranking().model_copy(update={'ranking_version':'first-'+str(uuid4())})
    second=first.model_copy(update={'ranking_version':'second-'+str(uuid4())})
    def game(tip,season='2026-2027'):
        e=evidence()
        return e.model_copy(update={'season':season,'ref':e.ref.model_copy(update={'day':tip.date(),'scheduled_at':tip})})
    try:
        async with factory.begin() as s:
            source=await s.get(SourceRecord,SOURCE_ID)
            if source is None:
                source=SourceRecord(id=SOURCE_ID,name='Synthetic manual source',kind='structured',adapter='manual_player_rankings',locator=SOURCE_URL,enabled=False,requires_auth=False,cadence_minutes=20160,verification_status='verified',retention_policy='normalized_full',adapter_settings={})
                s.add(source)
            source.adapter='manual_player_rankings';source.verification_status='verified';source.retention_policy='normalized_full'
            source.adapter_settings={'permission_reference':'synthetic-test-only','automated_access':False}
        async with factory.begin() as s:a=await store.import_snapshot(s,first,write=True)
        time[0]+=timedelta(days=1)
        async with factory.begin() as s:b=await store.import_snapshot(s,second,write=True)
        cutoff=time[0]+timedelta(days=1)
        past=game(datetime(2025,11,10,23,tzinfo=timezone.utc),'2025-2026')
        before=await counts(factory)
        async with factory() as s:
            assert (await store.read_snapshot(s,past,cutoff))['status']=='unavailable'
            retro=await store.read_snapshot(s,past,cutoff,fallback_to_first=True)
            assert retro['status']=='available' and retro['ranking_version']==first.ranking_version
            assert retro['retrospective'] and retro['cross_season_assumption']
            assert datetime.fromisoformat(retro['available_at'])==datetime.fromisoformat(a['observed_at'])
            assert retro['game_season']=='2025-2026' and retro['season']=='2026-2027'
            later=await store.read_snapshot(s,game(cutoff),cutoff,fallback_to_first=True)
            assert later['ranking_version']==second.ranking_version and not later['retrospective']
            assert (await store.read_snapshot(s,past,first_time-timedelta(days=1),fallback_to_first=True))['status']=='unavailable'
        assert await counts(factory)==before
        # Revoked/expired first snapshot does not silently select a later edition.
        async with factory.begin() as s:
            f=await s.scalar(select(TemporalFactRecord).where(TemporalFactRecord.fact_type==FACT_TYPE,TemporalFactRecord.value['ranking_version'].astext==first.ranking_version))
            f.valid_to=time[0]
        async with factory() as s:
            assert (await store.read_snapshot(s,past,cutoff,fallback_to_first=True))['status']=='unavailable'
        async with factory.begin() as s:
            f=await s.scalar(select(TemporalFactRecord).where(TemporalFactRecord.fact_type==FACT_TYPE,TemporalFactRecord.value['ranking_version'].astext==first.ranking_version))
            f.valid_to=None
            f.value={**f.value,'validation_status':'corrupted'}
        async with factory() as s:
            assert (await store.read_snapshot(s,past,cutoff,fallback_to_first=True))['status']=='unavailable'
    finally:await engine.dispose()
