"""The v4 proposal works from one game capture, with no season-history reads."""
from uuid import uuid4
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from integration.test_morning_persistence import setup, FixtureCollector
from test_game_records import evidence_with_records, DAY, NOW
from test_workbench import baseline
from nba_time_machine.db import TemporalFactRecord, RecommendationScoreRecord, SportsExternalIdentityRecord
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.workbench.app import app, CANDIDATE_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig

pytestmark = [pytest.mark.integration,pytest.mark.asyncio]


async def test_record_only_inspection_never_requires_history_and_preserves_archive(monkeypatch):
    import nba_time_machine.workbench.service as service
    async def forbidden(*args,**kwargs):
        raise AssertionError('v4 must not query or reconstruct season history')
    monkeypatch.setattr(service,'read_context',forbidden)
    engine,factory=await setup()
    try:
        e=evidence_with_records(str(uuid4().int)[:12])
        result=await MorningStore(factory,manual=True).collect(FixtureCollector([e]),DAY)
        assert result.captures_written==1
        cursor=NOW+timedelta(hours=1)
        async with factory.begin() as session:
            game=await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key=='espn', SportsExternalIdentityRecord.entity_type=='game',
                SportsExternalIdentityRecord.external_id==e.external_id))
            assert await MorningRankingPipeline(session).process(game,as_of=cursor,write=True)
        app.state.session_factory=factory
        app.state.baseline=baseline()
        app.state.candidate=TuningConfig.model_validate_json(CANDIDATE_CONFIG.read_text())
        async with factory() as session:
            before=[await session.scalar(select(func.count()).select_from(model)) for model in (TemporalFactRecord,RecommendationScoreRecord)]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1)),base_url='http://127.0.0.1:8765') as client:
            response=await client.get('/api/slate',params={'date':str(DAY),'as_of':cursor.isoformat()})
            assert response.status_code==200
            item=next(g for g in response.json()['games'] if g['game_id']==str(game))
            assert item['context']['status']=='available' and item['context']['standings']==[]
            assert item['context']['source_method']=='game_records'
            assert item['context']['home']['wins']==6 and item['context']['away']['losses']==6
            assert item['experiment']['context_bonus']==0 and item['experiment']['coverage']=='complete'
            assert item['archived']['eligible']
        async with factory() as session:
            after=[await session.scalar(select(func.count()).select_from(model)) for model in (TemporalFactRecord,RecommendationScoreRecord)]
            assert before==after
    finally:
        await engine.dispose()
