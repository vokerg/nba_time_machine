"""Explicit action writes canonical evidence only; synthetic data on local Postgres."""
from sqlalchemy import func, select
import pytest
from integration.test_morning_persistence import setup, evidence, FixtureCollector, DAY
from nba_time_machine.db import RecommendationScoreRecord, TemporalFactRecord
from nba_time_machine.workbench import collection

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_explicit_job_persists_and_deduplicates_without_archiving_scores(monkeypatch):
    engine, factory = await setup()
    e = evidence()
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
        assert job.start(DAY)
        await job.task
        assert job.result['state'] == 'finished'
        assert job.result['captures_written'] == 1
        after = await counts()
        assert after[0] == before[0] + 1
        assert after[1] == before[1]
        assert job.start(DAY)
        await job.task
        assert job.result['captures_written'] == 0
        assert await counts() == after
    finally:
        await engine.dispose()
