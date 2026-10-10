"""Real PostgreSQL proof: historical observation ranking, identity and reveal isolation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.api.game_list import game_list_response
from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord,
    SourceRecord, TeamRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.spoilers.game_list import GameListService, SqlAlchemyGameSlateRepository
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.spoilers.service import GameDisclosureService
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService

CURSOR = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
TIP = datetime(2026, 10, 9, 0, 30, tzinfo=timezone.utc)  # Oct 8 20:30 ET
NEXT_TIP = datetime(2026, 10, 9, 5, tzinfo=timezone.utc)  # Oct 9 01:00 ET
FINAL = TIP + timedelta(hours=3)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_game_list_uses_pre_tip_asof_snapshot_not_later_outcomes():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    profile, other = uuid4(), uuid4()
    first, moved, backfill, finalized_only = (uuid4() for _ in range(4))
    season, home, away = uuid4(), uuid4(), uuid4()
    source = f"list-fixture-{uuid4()}"

    def observation(game_id, when, tip, status="scheduled", **kwargs):
        return GameObservationRecord(
            game_id=game_id, source_id=source,
            observed_at=when, available_at=when,
            status=status, scheduled_tip_at=tip, **kwargs,
        )

    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season, league="NBA", label=f"test-list-{season}"),
                TeamRecord(id=home, league="NBA", name="Home"),
                TeamRecord(id=away, league="NBA", name="Away"),
                SourceRecord(
                    id=source, name="List fixture", kind="structured",
                    adapter="fixture", category=[], locator="fixture://list",
                    enabled=False, verification_status="verified",
                    cadence_minutes=60, requires_auth=False,
                    retention_policy="metadata_only",
                ),
            ])
            await session.flush()
            session.add_all([
                GameRecord(id=gid, season_id=season, home_team_id=home, away_team_id=away)
                for gid in (first, moved, backfill, finalized_only)
            ])
            await session.flush()
            session.add_all([
                observation(first, CURSOR - timedelta(hours=1), TIP),
                observation(first, FINAL, TIP, status="final",
                            final_at=FINAL, home_score=110, away_score=104),
                # Latest pre-tip snapshot moved this game to the next NBA date.
                observation(moved, CURSOR - timedelta(hours=3), TIP),
                observation(moved, CURSOR - timedelta(hours=2), NEXT_TIP),
                # This schedule was first observed AFTER the timeline cursor.
                observation(backfill, CURSOR + timedelta(hours=1), TIP),
                # Historical final alone is not evidence of a known pregame game.
                observation(finalized_only, FINAL, TIP, status="final",
                            final_at=FINAL, home_score=120, away_score=119),
            ])
            await session.commit()

        async with factory() as session:
            clock = TimelineService(SqlAlchemyTimelineRepository(session))
            await clock.initialize(profile, CURSOR)
            await clock.initialize(other, CURSOR)

        async with factory() as session:
            clock = TimelineService(SqlAlchemyTimelineRepository(session))
            slates = SqlAlchemyGameSlateRepository(session)
            reader = SqlAlchemyGameSnapshotRepository(session)
            acks = SqlAlchemyGameAcknowledgementRepository(session)
            listing = GameListService(clock, slates, reader, acks)
            disclosure = GameDisclosureService(clock, reader, acks)
            before = game_list_response(await listing.list_games(profile, slate_date=date(2026, 10, 8)))
            assert [card.game_id for card in before.games] == [first]
            assert before.games[0].state == "sealed"
            assert before.games[0].home_team == "Home"
            assert before.games[0].scheduled_tip == TIP.isoformat()
            assert "home_score" not in before.model_dump_json()
            assert backfill not in await slates.game_ids_on_date(
                slate_date=date(2026, 10, 8), time_cursor=CURSOR,
            )
            # Changes in a pre-tip schedule are observed as of the cursor.
            next_day = game_list_response(await listing.list_games(profile, slate_date=date(2026, 10, 9)))
            assert [card.game_id for card in next_day.games] == [moved]

            await disclosure.reveal_full(profile, first)
            after = game_list_response(await listing.list_games(profile, slate_date=date(2026, 10, 8)))
            assert [card.game_id for card in after.games] == [first]
            assert after.games[0].state == "acknowledged"
            assert after.time_cursor == before.time_cursor == CURSOR
            assert game_list_response(await listing.list_games(other, slate_date=date(2026, 10, 8))).games[0].state == "sealed"
            assert (await clock.resume(profile)).time_cursor == CURSOR
            assert not await acks.is_acknowledged(other, first)
    finally:
        await engine.dispose()
