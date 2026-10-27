"""Explicit action writes canonical evidence only; synthetic data on local Postgres."""
from sqlalchemy import func, select
from datetime import timedelta
import pytest
from integration.test_morning_persistence import setup, evidence, FixtureCollector, DAY
from nba_time_machine.db import RecommendationScoreRecord, TemporalFactRecord
from nba_time_machine.workbench import collection

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_explicit_job_deduplicates_evidence_and_publishes_ratings(monkeypatch):
    engine, factory = await setup()
    async def no_foundation(*args, **kwargs):
        return {'status': 'unavailable'}
    monkeypatch.setattr(collection, 'ensure_foundation', no_foundation)
    e = evidence()
    day = DAY - timedelta(days=100)
    e = e.model_copy(update={'observed_at': e.observed_at-timedelta(days=100),
        'ref':e.ref.model_copy(update={'day':day, 'scheduled_at':e.ref.scheduled_at-timedelta(days=100)})})
    class Collector(FixtureCollector):
        def __init__(self, *args, **kwargs):
            super().__init__([e])
    monkeypatch.setattr(collection, 'MorningCollector', Collector)
    async def counts():
        async with factory() as session:
            return (await session.scalar(select(func.count()).select_from(TemporalFactRecord)),
                    await session.scalar(select(func.count()).select_from(RecommendationScoreRecord)))
    try:
        before = await counts()
        job = collection.DayVerification(factory)
        assert job.start(day)
        await job.task
        assert job.result['state'] == 'finished'
        assert job.result['captures_written'] == 1
        after = await counts()
        assert after[0] == before[0] + 2
        assert after[1] == before[1] + 1
        assert job.result['ratings']['eligible'] == 1
        assert job.start(day)
        await job.task
        assert job.result['captures_written'] == 0
        replay = await counts()
        assert replay[0] == after[0] and replay[1] == after[1] + 1
    finally:
        await engine.dispose()
