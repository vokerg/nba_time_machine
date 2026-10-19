"""Real SQL query budgets and evidence parity, using disposable PostgreSQL only."""
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select

from integration.test_morning_persistence import setup, evidence, FixtureCollector, NOW
from nba_time_machine.api.viewing_guide import router
from nba_time_machine.db import SportsExternalIdentityRecord
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_guide_read_queries_do_not_grow_per_game_or_repeat_derivation():
    engine, factory = await setup()
    # Separate from the historical fixtures' dates; each season distinguishes
    # synthetic games sharing the same two fixture teams and scheduled tip.
    day = date(2026, 7, 1) + timedelta(days=uuid4().int % 28)
    cutoff = NOW - timedelta(days=1)
    profile = uuid4()
    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(router)
    statements = []

    def count_reads(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    async def seed(count):
        values = []
        for _ in range(count):
            e = evidence()
            values.append(e.model_copy(update={"season": "perf-" + str(uuid4()),
                "ref": e.ref.model_copy(update={"day": day,
                    "scheduled_at": e.ref.scheduled_at + timedelta(days=(day - e.ref.day).days)})}))
        report = await MorningStore(factory, manual=True).collect(FixtureCollector(values), day)
        assert report.captures_written == count
        async with factory.begin() as session:
            ids = tuple((await session.scalars(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key == "espn",
                SportsExternalIdentityRecord.entity_type == "game",
                SportsExternalIdentityRecord.external_id.in_([e.external_id for e in values])))).all())
            assert len(ids) == count
            for gid in ids:
                assert await MorningRankingPipeline(session).process(gid, as_of=NOW + timedelta(hours=1), write=True)
        return ids

    try:
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cutoff)
        first, = await seed(1)
        event.listen(engine.sync_engine, "before_cursor_execute", count_reads)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/profiles/{profile}/guide"
            body = {"date": str(day), "mode": "browse", "time_cursor": cutoff.isoformat(),
                    "level": "order", "consent": True}
            statements.clear()
            one = await client.post(path + "/disclose", json=body)
            assert one.status_code == 200 and one.json()["game_ids"] == [str(first)]
            one_reads = len(statements)
            await seed(7)
            for level, gid, expected_derivations in [("order", None, 8), ("order", None, 0),
                                                      ("verdict", first, 0), ("full", first, 0),
                                                      ("full", None, 0)]:
                statements.clear()
                with patch("nba_time_machine.ranking.morning_pipeline.trajectory_features",
                           wraps=trajectory_features) as derive:
                    response = await client.post(path + "/disclose", json={**body, "level": level,
                        **({"game_id": str(gid)} if gid else {})})
                    assert response.status_code == 200, response.text
                    assert derive.call_count == expected_derivations  # archive + guide share verification
                assert len(statements) == (one_reads if expected_derivations else 3)
                # One additional batched read preserves genuine pre-tip records.
                assert one_reads <= 16
                data = response.json()
                if level == "order":
                    assert len(data["game_ids"]) == 8 and data["details"] == {}
                elif level == "verdict":
                    assert set(data["details"][str(first)]) == {"game_id", "verdict", "has_clue"}
                else:
                    assert all("rating" in d and "result" in d for d in data["details"].values())
            statements.clear()
            safe = await client.get(path, params={"date": str(day), "mode": "browse"})
            assert safe.status_code == 200 and len(safe.json()["games"]) == 8
            assert len(statements) == 2
            assert all("rating" not in g and "result" not in g for g in safe.json()["games"])
        # Cached snapshots remain specific to the cutoff, even inside one reader.
        async with factory() as session:
            reader = SqlAlchemyGameSnapshotRepository(session, observed_schedule=True,
                knowledge_bounded=True, cache_snapshots=True)
            known = await reader.get_many((first,), time_cursor=NOW + timedelta(hours=1))
            assert known[first].full_available
            earlier = await reader.get(first, time_cursor=cutoff)
            assert not earlier.full_available
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_reads)
        await engine.dispose()
