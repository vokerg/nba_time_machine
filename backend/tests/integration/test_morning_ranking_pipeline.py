"""Capture -> reproducible features -> archived score -> gated coarse verdict."""
from datetime import timedelta
from uuid import uuid4

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import select

from integration.test_morning_persistence import setup, evidence, FixtureCollector, DAY, NOW
from nba_time_machine.db import (
    RecommendationScoreRecord, SourceRecord, SportsExternalIdentityRecord, TemporalFactRecord,
)
from nba_time_machine.ranking.morning_pipeline import BUNDLE_TYPE, MorningRankingPipeline
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.ranking.disclosure import ranking_fields
from nba_time_machine.ranking.config import RankingDisclosureSettings
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.api.game_disclosure import router as disclosure_router
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def capture(factory):
    e = evidence().model_copy(update={"season": "ranking-" + str(uuid4())})
    report = await MorningStore(factory, manual=True).collect(FixtureCollector([e]), DAY)
    assert report.captures_written == 1
    async with factory() as session:
        game = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == "espn",
            SportsExternalIdentityRecord.entity_type == "game",
            SportsExternalIdentityRecord.external_id == e.external_id))
    return game, e


async def test_dry_run_idempotent_materialization_and_temporal_visibility():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            pipeline = MorningRankingPipeline(session)
            assert not await pipeline.process(game, as_of=NOW - timedelta(seconds=1))
            assert await pipeline.process(game, as_of=cursor)
            assert not await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == game))
            assert await pipeline.process(game, as_of=cursor, write=True)
            assert await pipeline.process(game, as_of=cursor, write=True)
        async with factory() as session:
            bundles = (await session.scalars(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game, TemporalFactRecord.fact_type == BUNDLE_TYPE))).all()
            assert len(bundles) == 1
            assert bundles[0].value["metrics"]["clutch_ms"] == 300_000
            assert bundles[0].fact_metadata["actual_final_at"] is None
            assert bundles[0].observed_at == bundles[0].available_at == NOW
            reader = SqlAlchemyPostgameScoreRepository(session)
            assert await reader.postgame_scores_as_of((game,), as_of=NOW) == ()
            scores = await reader.postgame_scores_as_of((game,), as_of=cursor)
            assert len(scores) == 1 and len(scores[0].components) == 4
            assert scores[0].components[0].source_ref.endswith(bundles[0].fact_metadata["input_fact_id"])
            # Existing disclosure bridge emits coarse fields, never a numeric score.
            fields = ranking_fields(scores[0], bands=RankingDisclosureSettings().bands())
            assert fields and all(isinstance(f.value, str) for f in fields)
        profile = uuid4()
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cursor)
        app = FastAPI()
        app.state.session_factory = factory
        app.include_router(disclosure_router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/profiles/{profile}/games/{game}/watchability")
            assert response.status_code == 200
            assert response.json() == {"game_id": str(game), "disclosure": "watchability",
                                       "watchability_verdict": "Lower priority"}
    finally:
        await engine.dispose()


async def test_new_partial_revision_masks_old_score_without_destroying_history():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
        corrected = e.model_copy(update={"observed_at": NOW + timedelta(hours=2),
            "pbp_errors": ("score_regression",)})
        await MorningStore(factory, manual=True).collect(FixtureCollector([corrected]), DAY)
        async with factory() as session:
            reader = SqlAlchemyPostgameScoreRepository(session)
            assert len(await reader.postgame_scores_as_of((game,), as_of=cursor)) == 1
            assert await reader.postgame_scores_as_of((game,), as_of=NOW + timedelta(hours=3)) == ()
            assert not await MorningRankingPipeline(session).process(game, as_of=NOW + timedelta(hours=3))
            assert await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == game)) is not None
    finally:
        await engine.dispose()


async def test_source_revocation_withholds_already_archived_rating():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
            source = await session.get(SourceRecord, SOURCE_IDS["espn"])
            source.verification_status = "unverified"
        async with factory() as session:
            assert await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((game,), as_of=cursor) == ()
    finally:
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_IDS["espn"])
            source.verification_status = "verified"
        await engine.dispose()


@pytest.mark.parametrize("fault", ["malformed", "identity", "expired", "ambiguous", "future"])
async def test_untrusted_latest_evidence_does_not_materialize(fault):
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game,
                TemporalFactRecord.fact_type == "provider_game_evidence"))
            if fault == "malformed":
                fact.value = {"broken": True}
            elif fault == "identity":
                fact.value = {**fact.value, "external_id": "unmapped-game"}
            elif fault == "expired":
                fact.valid_to = NOW + timedelta(minutes=1)
            elif fault == "future":
                fact.available_at = cursor + timedelta(minutes=1)
            else:
                session.add(TemporalFactRecord(subject_type="game", game_id=game,
                    source_id=fact.source_id, fact_type=fact.fact_type, value=fact.value,
                    observed_at=fact.observed_at, available_at=fact.available_at,
                    valid_from=fact.valid_from))
        async with factory.begin() as session:
            assert not await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
            assert await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == game)) is None
    finally:
        await engine.dispose()


async def test_complete_revision_requires_new_snapshot_then_is_available():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        before, after = NOW + timedelta(hours=1), NOW + timedelta(hours=3)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=before, write=True)
        revised = e.model_copy(update={"observed_at": NOW + timedelta(hours=2),
                                      "notes": ("synthetic_revision",)})
        await MorningStore(factory, manual=True).collect(FixtureCollector([revised]), DAY)
        async with factory.begin() as session:
            reader = SqlAlchemyPostgameScoreRepository(session)
            assert await reader.postgame_scores_as_of((game,), as_of=after) == ()
            assert await MorningRankingPipeline(session).process(game, as_of=after, write=True)
            assert len(await reader.postgame_scores_as_of((game,), as_of=before)) == 1
            assert len(await reader.postgame_scores_as_of((game,), as_of=after)) == 1
            rows = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game))).all()
            assert len(rows) == 2
    finally:
        await engine.dispose()
