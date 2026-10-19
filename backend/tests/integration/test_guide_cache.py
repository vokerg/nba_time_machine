"""Cache reuse must never turn corrected or revoked records into trusted facts."""
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from integration.test_morning_persistence import setup, evidence, FixtureCollector, NOW
from nba_time_machine.api.viewing_guide import router
from nba_time_machine.db import (GameObservationRecord, RecommendationScoreRecord,
    SourceRecord, SportsExternalIdentityRecord, TemporalFactRecord)
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.spoilers.guide_cache import guide_revision
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def seed(factory):
    day = date(2026, 6, 1) + timedelta(days=uuid4().int % 28)
    e = evidence()
    e = e.model_copy(update={"season": "cache-" + str(uuid4()),
        "ref": e.ref.model_copy(update={"day": day,
            "scheduled_at": e.ref.scheduled_at + timedelta(days=(day - e.ref.day).days)})})
    await MorningStore(factory, manual=True).collect(FixtureCollector([e]), day)
    async with factory.begin() as session:
        gid = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == "espn",
            SportsExternalIdentityRecord.entity_type == "game",
            SportsExternalIdentityRecord.external_id == e.external_id))
        assert await MorningRankingPipeline(session).process(gid, as_of=NOW + timedelta(hours=1), write=True)
    return day, gid


@pytest.mark.parametrize("change", ["source", "retention", "observation", "evidence", "delete_evidence", "archive", "mapping"])
async def test_warm_cache_invalidates_committed_in_place_edits_and_deletions(change):
    engine, factory = await setup()
    try:
        day, gid = await seed(factory)
        profile, cursor = uuid4(), NOW - timedelta(days=1)
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cursor)
        app = FastAPI()
        app.state.session_factory = factory
        app.include_router(router)
        body = {"date": str(day), "mode": "browse", "time_cursor": cursor.isoformat(),
                "level": "verdict", "game_id": str(gid), "consent": True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/profiles/{profile}/guide/disclose"
            first = await client.post(path, json=body)
            assert first.status_code == 200 and "verdict" in first.json()["details"][str(gid)]
            with patch("nba_time_machine.ranking.morning_pipeline.trajectory_features", wraps=trajectory_features) as derive:
                again = await client.post(path, json=body)
                assert again.status_code == 200 and "verdict" in again.json()["details"][str(gid)]
                assert derive.call_count == 0
            async with factory.begin() as session:
                if change in ("source", "retention"):
                    row = await session.get(SourceRecord, SOURCE_IDS["espn"])
                    if change == "source":
                        row.verification_status = "unverified"
                    else:
                        row.retention_policy = "metadata_only"
                elif change == "observation":
                    row = await session.scalar(select(GameObservationRecord).where(GameObservationRecord.game_id == gid))
                    row.status = "in_progress"
                elif change in ("evidence", "delete_evidence"):
                    row = await session.scalar(select(TemporalFactRecord).where(
                        TemporalFactRecord.game_id == gid, TemporalFactRecord.fact_type == "provider_game_evidence"))
                    if change == "evidence":
                        row.value = {"broken": True}
                    else:
                        await session.delete(row)
                elif change == "archive":
                    row = await session.scalar(select(RecommendationScoreRecord).where(RecommendationScoreRecord.game_id == gid))
                    row.score_value = 9.99
                else:
                    await session.execute(delete(SportsExternalIdentityRecord).where(
                        SportsExternalIdentityRecord.game_id == gid))
            corrected = await client.post(path, json=body)
            assert corrected.status_code == 200
            assert set(corrected.json()["details"][str(gid)]) == {"game_id"}
            assert not corrected.json()["game_ids"]
    finally:
        if change in ("source", "retention"):
            async with factory.begin() as session:
                source = await session.get(SourceRecord, SOURCE_IDS["espn"])
                source.verification_status = "verified"
                source.retention_policy = "normalized_full"
        await engine.dispose()


async def test_revision_changes_when_time_eligibility_or_fact_validity_changes_without_writes():
    engine, factory = await setup()
    try:
        _, gid = await seed(factory)
        async with factory.begin() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == gid, TemporalFactRecord.fact_type == "provider_game_evidence"))
            fact.valid_from = NOW + timedelta(minutes=10)
            fact.valid_to = NOW + timedelta(minutes=20)
        async with factory() as session:
            times = [NOW - timedelta(seconds=1), NOW, NOW + timedelta(minutes=10),
                     NOW + timedelta(minutes=20), NOW + timedelta(hours=1)]
            revisions = [await guide_revision(session, at) for at in times]
            assert len(set(revisions)) == len(times)
            # Other shared fixtures can have eligibility boundaries near NOW.
            # Beyond all fixture dates, advancing the clock alone is no change.
            future = NOW + timedelta(days=36500)
            assert await guide_revision(session, future) == await guide_revision(session, future + timedelta(minutes=1))
    finally:
        await engine.dispose()
