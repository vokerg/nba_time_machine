"""Postgres/API regression for #90: intent never unlocks future NBA information."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from nba_time_machine.api.watch_queue import router as queue_router
from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord,
    SourceRecord, TeamRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService

CURSOR = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
TIP = datetime(2026, 10, 9, 0, 30, tzinfo=timezone.utc)  # October 8 ET
FUTURE_TIP = TIP + timedelta(days=1)
FINAL = TIP + timedelta(hours=3)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_persists_order_state_and_sealed_cards_without_cursor_side_effects():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    profile, other, season, home, away, first, future, missing, posttip = (uuid4() for _ in range(9))
    source = f"watch-queue-fixture-{uuid4()}"
    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(queue_router)
    base = f"/profiles/{profile}/watch-queue"
    other_base = f"/profiles/{other}/watch-queue"
    params = {"time_cursor": CURSOR.isoformat()}

    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season, league="NBA", label=f"queue-test-{season}"),
                TeamRecord(id=home, league="NBA", name="Home"),
                TeamRecord(id=away, league="NBA", name="Away"),
                SourceRecord(
                    id=source, name="Queue fixture", kind="sports", adapter="fixture",
                    category=[], locator="fixture://queue", enabled=False,
                    verification_status="verified", cadence_minutes=60,
                    requires_auth=False, retention_policy="metadata_only",
                ),
            ])
            await session.flush()
            session.add_all([
                GameRecord(id=game_id, season_id=season, home_team_id=home, away_team_id=away)
                for game_id in (first, future, missing, posttip)
            ])
            await session.flush()
            session.add_all([
                GameObservationRecord(
                    game_id=first, source_id=source, observed_at=CURSOR - timedelta(hours=1),
                    available_at=CURSOR - timedelta(hours=1),
                    status="scheduled", scheduled_tip_at=TIP,
                ),
                GameObservationRecord(
                    game_id=first, source_id=source, observed_at=FINAL,
                    available_at=FINAL, status="final", scheduled_tip_at=TIP,
                    final_at=FINAL, home_score=140, away_score=121,
                ),
                GameObservationRecord(
                    game_id=future, source_id=source, observed_at=CURSOR - timedelta(hours=1),
                    available_at=CURSOR - timedelta(hours=1),
                    status="scheduled", scheduled_tip_at=FUTURE_TIP,
                ),
                # Only post-tip evidence: observed/pregame must not backdate it.
                GameObservationRecord(
                    game_id=posttip, source_id=source, observed_at=FINAL,
                    available_at=FINAL, status="final", scheduled_tip_at=TIP,
                    home_score=130, away_score=101,
                ),
            ])
            await session.commit()
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            await timeline.initialize(profile, CURSOR)
            await timeline.initialize(other, CURSOR)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            assert (await client.get(base, params=params)).json() == {
                "time_cursor": CURSOR.isoformat().replace("+00:00", "Z"),
                "items": [],
            }
            for game_id in (first, future, missing):
                result = await client.put(f"{base}/{game_id}", json={
                    "time_cursor": CURSOR.isoformat(), "queue_state": "queued",
                })
                assert result.status_code == 204
            # Idempotent updates cannot reorder the queue or imply acknowledgement.
            for state in ("done", "done", "dismissed", "queued"):
                result = await client.put(f"{base}/{first}", json={
                    "time_cursor": CURSOR.isoformat(), "queue_state": state,
                })
                assert result.status_code == 204
            body = (await client.get(base, params=params)).json()
            assert [entry["game_id"] for entry in body["items"]] == [
                str(first), str(future), str(missing), str(posttip),
            ]
            assert body["items"][0]["queue_state"] == "queued"
            assert body["items"][0]["game"]["state"] == "sealed"
            assert body["items"][0]["game"]["home_team"] == "Home"
            assert body["items"][1]["game"] is None  # Future Eastern day.
            assert body["items"][2]["game"] is None  # No observations.
            assert body["items"][3]["game"]["home_team"] == "Home"  # Explicit retrospective replay.
            wire = str(body)
            for forbidden in ("140", "121", "130", "101", "home_score", "away_score", "result",
                              "watchability", "thumbnail", "runtime"):
                assert forbidden not in wire
            assert (await client.get(other_base, params=params)).json()["items"] == []
            observed = (await client.get(base, params={**params, "view": "observed"})).json()
            assert observed["items"][0]["game"]["state"] == "sealed"
            assert observed["items"][3]["game"] is None
            strict = (await client.get(base, params={**params, "view": "pregame"})).json()
            assert strict["items"][3]["game"] is None
            assert (await client.get(base, params={**params, "view": "unsafe"})).status_code == 422
            assert (await client.put(f"{base}/{first}", json={
                "time_cursor": CURSOR.isoformat(), "queue_state": "acknowledged",
            })).status_code == 422
            assert (await client.put(f"{base}/{first}", json={
                "time_cursor": CURSOR.isoformat(), "queue_state": "done",
                "home_score": 100,
            })).status_code == 422
            stale = {"time_cursor": (CURSOR + timedelta(hours=1)).isoformat()}
            assert (await client.get(base, params=stale)).status_code == 409
            assert (await client.put(f"{base}/{first}", json={
                **stale, "queue_state": "done",
            })).status_code == 409
            assert (await client.delete(f"{base}/{first}", params=stale)).status_code == 409
            assert (await client.put(f"{base}/{uuid4()}", json={
                "time_cursor": CURSOR.isoformat(), "queue_state": "queued",
            })).status_code == 404
            assert (await client.delete(f"{base}/{first}", params=params)).status_code == 204
            assert (await client.delete(f"{base}/{first}", params=params)).status_code == 204
            remaining = (await client.get(base, params=params)).json()["items"]
            assert [item["game_id"] for item in remaining] == [str(future), str(missing), str(posttip)]
        async with factory() as session:
            timeline = TimelineService(SqlAlchemyTimelineRepository(session))
            assert (await timeline.resume(profile)).time_cursor == CURSOR
            assert (await timeline.resume(other)).time_cursor == CURSOR
            acks = SqlAlchemyGameAcknowledgementRepository(session)
            assert not await acks.is_acknowledged(profile, first)
            assert not await acks.is_acknowledged(profile, future)
            assert not await acks.is_acknowledged(other, first)
    finally:
        await engine.dispose()
