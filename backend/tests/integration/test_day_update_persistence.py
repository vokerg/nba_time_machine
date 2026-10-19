"""One UI action persists evidence and publishes ratings on disposable PostgreSQL."""
from datetime import date, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from integration.test_morning_persistence import setup, evidence, FixtureCollector, NOW
from nba_time_machine.api.day_update import router
from nba_time_machine.api.viewing_guide import router as guide_router
from nba_time_machine.db import CollectionRunRecord, GameAcknowledgementRecord, RecommendationScoreRecord, TemporalFactRecord
from nba_time_machine.sports import day_update
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_explicit_http_update_captures_archives_refreshes_safe_slate_and_never_advances_cursor(monkeypatch):
    engine, factory = await setup()
    day = date(2026, 8, 1) + timedelta(days=uuid4().int % 28)
    value = evidence()
    value = value.model_copy(update={"season": "update-" + str(uuid4()), "ref": value.ref.model_copy(update={
        "day": day, "scheduled_at": value.ref.scheduled_at + timedelta(days=(day - value.ref.day).days)})})
    class Collector(FixtureCollector):
        def __init__(self, *args, **kwargs):
            super().__init__([value])
        async def collect(self, *args, **kwargs):
            report = await super().collect(*args, **kwargs)
            report.discovery = "espn"
            return report
    monkeypatch.setattr(day_update, "MorningCollector", Collector)
    profile, cursor = uuid4(), NOW - timedelta(days=3)
    app = FastAPI()
    app.state.session_factory = factory
    jobs = app.state.day_updates = day_update.DayUpdateJobs(factory)
    app.include_router(router)
    app.include_router(guide_router)
    try:
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cursor)
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            base = f"/profiles/{profile}/guide"
            payload = {"date": day.isoformat(), "mode": "browse", "time_cursor": cursor.isoformat()}
            # Stale cursors and future dates fail before invoking a collector.
            headers = {"X-Guide-Action": "update-day"}
            assert (await client.post(base + "/update", json={**payload, "time_cursor": NOW.isoformat()}, headers=headers)).status_code == 409
            assert jobs.task is None
            response = await client.post(base + "/update", json=payload, headers=headers)
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            await jobs.task
            status = await client.get(base + "/update/" + job_id)
            assert status.json() == {"job_id": job_id, "date": day.isoformat(), "state": "finished"}
            safe = await client.get(base, params={"date": day.isoformat(), "mode": "browse"})
            assert safe.status_code == 200 and safe.json()["games"]
            assert all("rating" not in card and "home_score" not in card for card in safe.json()["games"])
            order = await client.post(base + "/disclose", json={**payload, "consent": True, "level": "order"})
            assert order.status_code == 200 and order.json()["game_ids"]
            game = UUID(order.json()["game_ids"][0])
            async with factory() as session:
                assert await session.scalar(select(RecommendationScoreRecord.id).where(RecommendationScoreRecord.game_id == game))
                assert (await TimelineService(SqlAlchemyTimelineRepository(session)).resume(profile)).time_cursor == cursor
                assert not await session.scalar(select(GameAcknowledgementRecord.game_id).where(GameAcknowledgementRecord.profile_id == profile))
                runs = (await session.scalars(select(CollectionRunRecord).order_by(CollectionRunRecord.started_at.desc()))).all()
                assert any(run.run_metadata.get("rating_update", {}).get("eligible", 0) >= 1 for run in runs)
                before = await session.scalar(select(func.count()).select_from(TemporalFactRecord).where(
                    TemporalFactRecord.game_id == game, TemporalFactRecord.fact_type == "provider_game_evidence"))
            # Repeat is safe: identical captures deduplicate; valid archive snapshots stay append-only.
            assert (await client.post(base + "/update", json=payload, headers=headers)).status_code == 202
            await jobs.task
            assert jobs.result["state"] == "finished"
            async with factory() as session:
                after = await session.scalar(select(func.count()).select_from(TemporalFactRecord).where(
                    TemporalFactRecord.game_id == game, TemporalFactRecord.fact_type == "provider_game_evidence"))
                assert before == after
    finally:
        await jobs.close()
        await engine.dispose()
