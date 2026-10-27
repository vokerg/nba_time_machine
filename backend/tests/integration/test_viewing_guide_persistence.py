"""Actual PostgreSQL proof of independent Browse and strict bulk disclosures."""
from datetime import date, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from integration.test_morning_persistence import setup, NOW, evidence, FixtureCollector
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.db import SportsExternalIdentityRecord
from nba_time_machine.api.viewing_guide import router
from nba_time_machine.db import GameObservationRecord, GameAcknowledgementRecord, RecommendationScoreRecord
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_imported_slate_ratings_bulk_reveal_and_cross_mode_cursor_isolation():
    engine, factory = await setup()
    try:
        # Use an isolated synthetic day so unrelated integration fixtures cannot
        # exceed the real 32-game date bound when tests share a database.
        day = date(2026, 8, 1) + timedelta(days=uuid4().int % 28)
        e = evidence()
        e = e.model_copy(update={"season": "guide-" + str(uuid4()), "ref": e.ref.model_copy(update={
            "day": day, "scheduled_at": e.ref.scheduled_at + timedelta(days=(day - e.ref.day).days)})})
        report = await MorningStore(factory, manual=True).collect(FixtureCollector([e]), day)
        assert report.captures_written == 1
        async with factory() as session:
            game = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.provider_key == "espn",
                SportsExternalIdentityRecord.entity_type == "game",
                SportsExternalIdentityRecord.external_id == e.external_id))
        cutoff = NOW - timedelta(days=3)
        profile = uuid4()
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cutoff)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=NOW + timedelta(hours=1), write=True)
        app = FastAPI()
        app.state.session_factory = factory
        app.include_router(router)
        base = f"/profiles/{profile}/guide"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            safe = (await client.get(base, params={"date": day.isoformat(), "mode": "browse"})).json()
            assert str(game) in [g["game_id"] for g in safe["games"]]
            assert datetime.fromisoformat(safe["time_cursor"]) == cutoff
            card = next(g for g in safe["games"] if g["game_id"] == str(game))
            assert set(card) == {"game_id", "state", "disclosure", "home_team", "away_team", "scheduled_tip"}
            assert card["state"] == "sealed"
            strict = (await client.get(base, params={"date": day.isoformat(), "mode": "time-machine"})).json()
            assert str(game) not in [g["game_id"] for g in strict["games"]]
            body = {"date": day.isoformat(), "mode": "browse", "time_cursor": cutoff.isoformat(), "level": "order", "consent": True}
            ranked = await client.post(base + "/disclose", json=body)
            assert ranked.status_code == 200
            assert str(game) in ranked.json()["game_ids"]
            assert ranked.json()["details"] == {}
            full = await client.post(base + "/disclose", json={**body, "level": "full"})
            assert full.status_code == 200
            detail = full.json()["details"][str(game)]
            assert "result" in detail and "rating" in detail and detail["components"]
            assert sum(c["points"] for c in detail["components"]) == pytest.approx(detail["rating"], abs=.001)
            # An opened game is still absent before its first observation in strict mode.
            strict_reveal = await client.post(base + "/disclose", json={**body, "mode": "time-machine", "level": "full", "game_id": str(game)})
            assert strict_reveal.status_code == 403
            async with factory() as session:
                assert (await TimelineService(SqlAlchemyTimelineRepository(session)).resume(profile)).time_cursor == cutoff
                assert await session.scalar(select(GameAcknowledgementRecord.game_id).where(GameAcknowledgementRecord.profile_id == profile, GameAcknowledgementRecord.game_id == game)) == game
                assert await session.scalar(select(RecommendationScoreRecord.id).where(RecommendationScoreRecord.game_id == game))
            # A newer nonfinal revision masks the result, but the saved rating
            # persists until explicit recalculation.
            async with factory.begin() as session:
                latest = await session.scalar(select(GameObservationRecord).where(GameObservationRecord.game_id == game).order_by(GameObservationRecord.observed_at.desc()))
                session.add(GameObservationRecord(game_id=game, source_id=latest.source_id,
                    observed_at=NOW + timedelta(hours=2), available_at=NOW + timedelta(hours=2),
                    status="scheduled", scheduled_tip_at=latest.scheduled_tip_at))
            corrected = await client.post(base + "/disclose", json={**body, "level": "full", "game_id": str(game)})
            assert corrected.status_code == 200
            assert "result" not in corrected.json()["details"][str(game)]
            assert corrected.json()["details"][str(game)]["rating"] == detail["rating"]
    finally:
        await engine.dispose()
