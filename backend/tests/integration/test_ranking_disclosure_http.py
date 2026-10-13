"""Synthetic archive evidence through actual SQL readers and HTTP projections."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from nba_time_machine.api.game_disclosure import router as disclosure_router
from nba_time_machine.api.game_list import router as list_router
from nba_time_machine.api.recommendations import router as recommendation_router
from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord, SourceRecord,
    TeamRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.ranking.repository import SqlAlchemyRankingStore
from nba_time_machine.ranking.scoring import FeatureObservation, PostgameSignal, score_postgame
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_archived_scores_drive_only_explicit_http_picks_and_coarse_verdicts():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    tip = datetime(2026, 5, 5, 1, tzinfo=timezone.utc)
    before, final = tip - timedelta(hours=2), tip + timedelta(hours=3)
    season, home, away, ordinary, exceptional, profile = [uuid4() for _ in range(6)]
    source = f"ranking-http-{uuid4()}"
    app = FastAPI()
    app.state.session_factory = factory
    for router in (disclosure_router, list_router, recommendation_router):
        app.include_router(router)
    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season, league="NBA", label="ranking-http-test"),
                TeamRecord(id=home, league="NBA", name="Home"),
                TeamRecord(id=away, league="NBA", name="Away"),
                SourceRecord(id=source, name="Synthetic ranking fixture", kind="sports",
                             adapter="fixture", category=[], locator="fixture://nba",
                             enabled=False, verification_status="verified", cadence_minutes=60,
                             requires_auth=False, retention_policy="metadata_only"),
            ])
            await session.flush()
            for game in (ordinary, exceptional):
                session.add(GameRecord(id=game, season_id=season, home_team_id=home, away_team_id=away))
            await session.flush()
            for game, value in ((ordinary, .2), (exceptional, .9)):
                session.add_all([
                    GameObservationRecord(game_id=game, source_id=source, status="scheduled",
                                          scheduled_tip_at=tip, observed_at=before, available_at=before),
                    GameObservationRecord(game_id=game, source_id=source, status="final",
                                          scheduled_tip_at=tip, final_at=final,
                                          observed_at=final, available_at=final,
                                          home_score=110, away_score=108),
                ])
                await SqlAlchemyRankingStore(session).archive(score_postgame(
                    game, {PostgameSignal.CLUTCH: FeatureObservation(value, "synthetic:fact", final, final)},
                    final_at=final, as_of=final,
                ))
            await session.commit()
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, before)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            base = f"/profiles/{profile}"
            payload = {"slate_date": "2026-05-04", "candidate_game_ids": [str(ordinary), str(exceptional)]}
            assert (await client.post(base + "/recommendations/watchability", json=payload)).status_code == 403
            early = await client.get(base + f"/games/{exceptional}/watchability")
            assert early.json() == {"game_id": str(exceptional), "disclosure": "watchability"}
            consented = {**payload, "consent_to_outcome_ranking": True}
            assert (await client.post(base + "/recommendations/watchability", json=consented)).json() == {"game_ids": []}
            async with factory() as session:
                await TimelineService(SqlAlchemyTimelineRepository(session)).advance(profile, final)
            slate_before = (await client.get(base + "/games?date=2026-05-04")).json()
            ranked = await client.post(base + "/recommendations/watchability", json=consented)
            assert ranked.json() == {"game_ids": [str(exceptional), str(ordinary)]}
            budgeted = await client.post(base + "/recommendations/watchability", json={
                **consented, "budget_minutes": 120, "planned_minutes_per_game": 120,
            })
            assert budgeted.json() == {"game_ids": [str(exceptional)]}
            verdict = (await client.get(base + f"/games/{exceptional}/watchability")).json()
            assert verdict == {"game_id": str(exceptional), "disclosure": "watchability",
                               "watchability_verdict": "Worth watching"}
            why = (await client.get(base + f"/games/{exceptional}/why")).json()
            assert why == {**verdict, "disclosure": "why"}
            assert (await client.get(base + "/games?date=2026-05-04")).json() == slate_before
        async with factory() as session:
            assert (await TimelineService(SqlAlchemyTimelineRepository(session)).resume(profile)).time_cursor == final
            acks = SqlAlchemyGameAcknowledgementRepository(session)
            assert not await acks.is_acknowledged(profile, ordinary)
            assert not await acks.is_acknowledged(profile, exceptional)
    finally:
        await engine.dispose()
