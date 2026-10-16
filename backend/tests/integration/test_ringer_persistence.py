"""Mock HTTP and synthetic names on disposable Postgres; no live publisher list."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from integration.test_morning_persistence import setup
from test_ringer import page
from nba_time_machine.db import SourceRecord, TemporalFactRecord, RawCaptureRecord
from nba_time_machine.ingestion import ringer
from nba_time_machine.ranking import player_ranking_store
from nba_time_machine.ranking.player_rankings import SOURCE_ID, FACT_TYPE
pytestmark=[pytest.mark.integration,pytest.mark.asyncio]

async def configure(factory):
    await ringer.configure_hobby_source(factory)
    async with factory.begin() as session:
        source=await session.get(SourceRecord,SOURCE_ID)
        source.runtime_cursor=None
        source.verification_status='unverified'

async def test_one_concurrent_check_and_durable_interval_after_restart(monkeypatch):
    engine,factory=await setup()
    try:
        await configure(factory)
        async def catalog(*args):
            return [{'espn_id':str(i),'name':f'Synthetic Player {i}','team':'BOS','fact_id':str(uuid4())} for i in range(1,101)]
        monkeypatch.setattr(player_ranking_store,'identity_catalog',catalog)
        requests=[]
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200,text=page())
        transport=httpx.MockTransport(respond)
        a,b=await asyncio.gather(ringer.refresh_if_due(factory,transport=transport),ringer.refresh_if_due(factory,transport=transport))
        assert sorted([a['state'],b['state']])==['not_due','ok']
        assert requests==[ringer.SOURCE_URL]
        assert (await ringer.refresh_if_due(factory,transport=transport))['state']=='not_due'
        async with factory() as session:
            status=await ringer.source_status(session)
            assert status['snapshot_coverage']['matched']==100
            assert status['access_basis']=='owner_directed_private_hobby'
            assert status['publisher_permission'] is False
            assert datetime.fromisoformat(status['next_check_at'])-datetime.fromisoformat(status['last_attempt_at'])==timedelta(days=14)
            latest=await session.scalar(select(TemporalFactRecord).where(TemporalFactRecord.fact_type==FACT_TYPE).order_by(TemporalFactRecord.observed_at.desc()).limit(1))
            assert latest.value['publication_status']=='unknown'
            capture=await session.scalar(select(RawCaptureRecord).where(RawCaptureRecord.source_id==SOURCE_ID).order_by(RawCaptureRecord.captured_at.desc()).limit(1))
            assert '<ol>' not in capture.text_content and capture.raw_payload is None
        async with factory.begin() as session:
            source=await session.get(SourceRecord,SOURCE_ID)
            source.runtime_cursor={**source.runtime_cursor,'attempted_at':(datetime.now(timezone.utc)-timedelta(days=15)).isoformat()}
        duplicate=await ringer.refresh_if_due(factory,transport=transport)
        assert not duplicate['result']['written']
    finally: await engine.dispose()

@pytest.mark.parametrize('http_status',[403,429,302])
async def test_access_failure_is_not_retried_and_no_redirect_followed(http_status):
    engine,factory=await setup()
    try:
        await configure(factory)
        calls=[]
        def blocked(request):
            calls.append(str(request.url))
            return httpx.Response(http_status,headers={'Location':'https://example.com'},text='private body')
        transport=httpx.MockTransport(blocked)
        result=await ringer.refresh_if_due(factory,transport=transport)
        assert result['code']==f'ringer_http_{http_status}'
        assert (await ringer.refresh_if_due(factory,transport=transport))['state']=='not_due'
        assert calls==[ringer.SOURCE_URL]
        assert 'private body' not in str(result)
    finally: await engine.dispose()

async def test_rosters_use_canonical_team_identity_and_feed_mapping_catalog(monkeypatch):
    from nba_time_machine.sports import player_identities as identities
    from nba_time_machine.sports.morning_models import TEAM_NAMES
    from nba_time_machine.ranking.player_ranking_store import identity_catalog
    from nba_time_machine.sports.morning import PublicNBAClient
    engine,factory=await setup()
    monkeypatch.setattr(identities,'COLLECTOR_VERSION','synthetic-roster-'+str(uuid4()))
    # No real rate-limit sleep is needed for in-memory fixtures.
    monkeypatch.setattr(identities,'PublicNBAClient',lambda http,**kw:PublicNBAClient(http,interval=0,**kw))
    calls=[]
    labels=list(TEAM_NAMES)
    first_id=1000000+uuid4().int%100000000
    monkeypatch.setattr(identities,'TEAM_NAMES',{a:'Synthetic '+str(first_id)+' '+a for a in labels})
    def response(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/teams'):
            return httpx.Response(200,json={'sports':[{'leagues':[{'teams':[{'team':{'id':str(i),'abbreviation':abbr}} for i,abbr in enumerate(labels,first_id)]}]}]})
        team_id=request.url.path.split('/')[-2]
        return httpx.Response(200,json={'team':{'id':team_id},'athletes':[{'id':str(90000+int(team_id)),'displayName':'Synthetic Roster Athlete '+team_id}]})
    try:
        result=await identities.collect_identities(factory,transport=httpx.MockTransport(response))
        assert result['identities']==30 and result['captures_written']==30 and not result['errors']
        assert len(calls)==31
        assert (await identities.collect_identities(factory,transport=httpx.MockTransport(response)))['state']=='not_due'
        assert len(calls)==31
        async with factory() as session:
            catalog=await identity_catalog(session,datetime.now(timezone.utc))
            assert any(r['espn_id']==str(90000+first_id) and r['team']==labels[0] and r['fact_id'] for r in catalog)
            facts=(await session.scalars(select(TemporalFactRecord).where(TemporalFactRecord.fact_type==identities.FACT_TYPE))).all()
            assert all(f.team_id is not None and f.fact_metadata['not_game_participation'] for f in facts)
    finally: await engine.dispose()

async def test_mapping_can_complete_without_refetching_ringer(monkeypatch):
    from nba_time_machine.sports import player_identities
    engine,factory=await setup()
    count=[50]
    async def catalog(*args):
        return [{'espn_id':str(i),'name':f'Synthetic Player {i}','team':'BOS','fact_id':'synthetic-mapping-evidence'} for i in range(1,count[0]+1)]
    async def identities(*args,**kwargs):
        count[0]=100
        return {'state':'synthetic_rosters_loaded'}
    monkeypatch.setattr(player_ranking_store,'identity_catalog',catalog)
    monkeypatch.setattr(player_identities,'collect_identities',identities)
    calls=[]
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200,text=page())
    try:
        await configure(factory)
        first=await ringer.refresh_if_due(factory,transport=httpx.MockTransport(response))
        assert first['result']['coverage']['matched']==50
        resolved=await ringer.complete_identities(factory)
        assert resolved['result']['coverage']['matched']==100
        assert resolved['result']['content_version']==first['result']['content_version']
        assert resolved['result']['revision_hash']!=first['result']['revision_hash']
        assert datetime.fromisoformat(resolved['result']['observed_at'])>datetime.fromisoformat(first['result']['observed_at'])
        assert calls==[ringer.SOURCE_URL]
    finally: await engine.dispose()
