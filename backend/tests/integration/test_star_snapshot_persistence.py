"""Synthetic permission, rankings and mappings on disposable PostgreSQL only."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from integration.test_morning_persistence import setup, FixtureCollector, DAY
from test_star_power import ranking, catalog, evidence as star_evidence
from test_game_records import evidence_with_records, DAY as RECORD_DAY, NOW
from test_workbench import baseline
from nba_time_machine.db import (SourceRecord, TemporalFactRecord, RawCaptureRecord,
    RecommendationScoreRecord, SportsExternalIdentityRecord, PlayerRecord)
from nba_time_machine.ranking.player_rankings import SOURCE_ID, SOURCE_URL, FACT_TYPE
from nba_time_machine.ranking.player_ranking_store import import_snapshot, read_snapshot, identity_catalog
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.workbench.app import app, CANDIDATE_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def counts(factory):
    async with factory() as session:
        return [await session.scalar(select(func.count()).select_from(m)) for m in
                (TemporalFactRecord, RawCaptureRecord, RecommendationScoreRecord, PlayerRecord)]


async def test_manual_import_versions_temporal_selection_and_revocation(monkeypatch):
    import nba_time_machine.ranking.player_ranking_store as store
    engine, factory = await setup()
    async def fake_catalog(*args): return catalog()
    monkeypatch.setattr(store, 'identity_catalog', fake_catalog)
    r = ranking().model_copy(update={"ranking_version": "synthetic-" + str(uuid4())})
    try:
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_ID)
            if source is None:
                source = SourceRecord(id=SOURCE_ID, name='Synthetic source', kind='structured',
                    adapter='manual_player_rankings', locator=SOURCE_URL, enabled=False,
                    verification_status='unverified', cadence_minutes=10080, requires_auth=False,
                    retention_policy='metadata_only', adapter_settings={})
                session.add(source)
            source.adapter='manual_player_rankings'
            source.verification_status="unverified"
            source.retention_policy="metadata_only"
            await session.flush()
            with pytest.raises(ValueError): await import_snapshot(session, r, write=True)
            source.verification_status='verified';source.retention_policy='normalized_full'
            source.adapter_settings={'permission_reference':'synthetic-test-only','automated_access':False}
        async with factory.begin() as session:
            dry=await import_snapshot(session, r)
            assert not dry['written'] and dry['coverage']['matched']==100
        before=await counts(factory)
        async with factory.begin() as session: a=await import_snapshot(session,r,write=True)
        async with factory.begin() as session: duplicate=await import_snapshot(session,r,write=True)
        assert a['written'] and not duplicate['written']
        after=await counts(factory)
        assert after[0]==before[0]+1 and after[1]==before[1]+1
        # Changing published content under the same edition label is a revision.
        swapped=(r.players[1].model_copy(update={'rank':1}),r.players[0].model_copy(update={'rank':2}))+r.players[2:]
        changed=r.model_copy(update={'players':swapped})
        async with factory.begin() as session: b=await import_snapshot(session,changed,write=True)
        assert b['written'] and b['content_version']!=a['content_version']
        async with factory.begin() as session: restored=await import_snapshot(session,r,write=True)
        assert restored['written'] # A -> B -> A must not resurrect an old fact timestamp
        # Later revisions must not affect a game that tipped after A but before B.
        first_tip = datetime.fromisoformat(b['observed_at'])
        midgame = star_evidence().model_copy(update={'ref':star_evidence().ref.model_copy(update={'scheduled_at':first_tip})})
        async with factory() as session:
            historical_a = await read_snapshot(session, midgame, datetime.now(timezone.utc))
            assert historical_a['status']=='available'
            assert historical_a['content_version']==a['content_version']
            assert datetime.fromisoformat(historical_a['observed_at'])==datetime.fromisoformat(a['observed_at'])
        async with factory() as session:
            e=star_evidence()
            e=e.model_copy(update={'ref':e.ref.model_copy(update={'scheduled_at':datetime.now(timezone.utc)-timedelta(days=1)})})
            historical=await read_snapshot(session,e,datetime.now(timezone.utc))
            assert historical['status']=='unavailable' # Imported today after fixture's tip.
            later=datetime.now(timezone.utc)+timedelta(days=1)
            e=e.model_copy(update={'ref':e.ref.model_copy(update={'scheduled_at':later})})
            current=await read_snapshot(session,e,later)
            assert current['status']=='available' and current['coverage']['matched']==100
            assert datetime.fromisoformat(current['observed_at'])>datetime.fromisoformat(a['observed_at'])
            assert current['published_date'] is None
            # Cursor before first capture cannot see any version, even for a later tip.
            assert (await read_snapshot(session,e,datetime(2020,1,1,tzinfo=timezone.utc)))['status']=='unavailable'
        async with factory.begin() as session:
            latest=await session.scalar(select(TemporalFactRecord).where(TemporalFactRecord.fact_type==FACT_TYPE).order_by(TemporalFactRecord.observed_at.desc()).limit(1))
            latest.value={**latest.value,'validation_status':'corrupted'}
        async with factory() as session:
            assert (await read_snapshot(session,e,later))['status']=='unavailable'
        async with factory.begin() as session:
            source=await session.get(SourceRecord,SOURCE_ID);source.retention_policy='metadata_only'
        async with factory() as session:
            assert (await read_snapshot(session,e,later))['status']=='unavailable'
    finally: await engine.dispose()


async def test_v5_preview_is_read_only_and_catalog_uses_stored_espn(monkeypatch):
    engine,factory=await setup()
    try:
        async with factory() as session:
            latest=await session.scalar(select(func.max(TemporalFactRecord.observed_at)).where(
                TemporalFactRecord.fact_type=='provider_game_evidence',
                TemporalFactRecord.value['ref']['day'].astext==str(RECORD_DAY)))
        observed=max(NOW+timedelta(minutes=30), latest+timedelta(seconds=1) if latest else NOW)
        cutoff=observed+timedelta(hours=1)
        e=evidence_with_records(str(uuid4().int)[:12]).model_copy(update={'observed_at':observed})
        await MorningStore(factory,manual=True).collect(FixtureCollector([e]),RECORD_DAY)
        async with factory() as session:
            mapped=await identity_catalog(session,cutoff)
            assert any(row['espn_id']==e.players[0].external_id and row['name']==e.players[0].name for row in mapped)
        app.state.session_factory=factory;app.state.baseline=baseline()
        app.state.candidate=TuningConfig.model_validate_json(CANDIDATE_CONFIG.read_text())
        before=await counts(factory)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1)),base_url='http://127.0.0.1:8765') as client:
            response=await client.post('/api/preview',json={'slate_date':str(RECORD_DAY),'as_of':(cutoff).isoformat(),'config':app.state.candidate.model_dump(exclude_none=True)})
            assert response.status_code==200
            item=next(g for g in response.json()['games'] if g['evidence'] and g['evidence']['external_id']==e.external_id)
            assert item['star_power']['status']=='unavailable' and item['experiment']['star_bonus'] is None
            assert 'star power' in item['experiment']['missing_families']
            assert item['context']['source_method']=='game_records'
        assert before==await counts(factory)
        async with factory() as session:
            async with session.begin():
                await session.execute(text('SET TRANSACTION READ ONLY'))
                with pytest.raises(DBAPIError): await session.execute(text("UPDATE sources SET name=name WHERE id=:id"),{'id':SOURCE_ID})
    finally: await engine.dispose()
