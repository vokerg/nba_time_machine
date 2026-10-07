from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nba_time_machine.db import (
    DatabaseSettings,
    GameObservationRecord,
    GameRecord,
    SourceRecord,
    SportsExternalIdentityRecord,
    create_database_engine,
    create_session_factory,
)
from nba_time_machine.sports.repository import StructuredSportsStore


def _settings_or_skip() -> DatabaseSettings:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


def _provider_source() -> SourceRecord:
    return SourceRecord(
        id="thesportsdb-nba",
        name="TheSportsDB NBA",
        kind="structured",
        adapter="thesportsdb",
        category=["third_party", "schedule", "games", "stats"],
        locator="https://www.thesportsdb.com/api/v1/json",
        enabled=False,
        verification_status="verified",
        cadence_minutes=10,
        requires_auth=False,
        retention_policy="normalized_full",
    )


def _event(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "idEvent": "2601626",
        "idLeague": "4387",
        "strSeason": "2026-2027",
        "idHomeTeam": "134873",
        "strHomeTeam": "Indiana Pacers",
        "idAwayTeam": "134886",
        "strAwayTeam": "Minnesota Timberwolves",
        "strEvent": "Indiana Pacers vs Minnesota Timberwolves",
        "strStatus": "NS",
        "strPostponed": "no",
        "strTimestamp": "2026-10-07T23:00:00",
        "dateEvent": "2026-10-07",
        "dateEventLocal": "2026-10-07",
        "strTime": "23:00:00",
        "strTimeLocal": "19:00:00",
        "intRound": "1",
        "intHomeScore": None,
        "intAwayScore": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schedule_and_final_observations_preserve_same_stable_game() -> None:
    engine = create_database_engine(_settings_or_skip())
    session_factory = create_session_factory(engine)
    store = StructuredSportsStore()
    first_observed_at = datetime.now(timezone.utc) - timedelta(hours=4)
    final_observed_at = first_observed_at + timedelta(hours=3)

    try:
        async with session_factory() as session:
            session.add(_provider_source())
            await session.commit()

        async with session_factory() as session:
            scheduled = await store.store_thesportsdb_event(
                session,
                _event(),
                observed_at=first_observed_at,
            )
            await session.commit()
            scheduled_game_id = scheduled.game_id

        async with session_factory() as session:
            final = await store.store_thesportsdb_event(
                session,
                _event(
                    strStatus="FT",
                    intHomeScore="111",
                    intAwayScore="108",
                ),
                observed_at=final_observed_at,
            )
            await session.commit()
            assert final.game_id == scheduled_game_id

        async with session_factory() as session:
            observations = (
                await session.scalars(
                    select(GameObservationRecord)
                    .where(GameObservationRecord.game_id == scheduled_game_id)
                    .order_by(GameObservationRecord.observed_at)
                )
            ).all()
            game_count = await session.scalar(
                select(func.count()).select_from(GameRecord)
            )
            game_identity_count = await session.scalar(
                select(func.count())
                .select_from(SportsExternalIdentityRecord)
                .where(
                    SportsExternalIdentityRecord.provider_key == "thesportsdb",
                    SportsExternalIdentityRecord.entity_type == "game",
                    SportsExternalIdentityRecord.external_id == "2601626",
                )
            )
            team_identity_count = await session.scalar(
                select(func.count())
                .select_from(SportsExternalIdentityRecord)
                .where(
                    SportsExternalIdentityRecord.provider_key == "thesportsdb",
                    SportsExternalIdentityRecord.entity_type == "team",
                )
            )

        assert game_count == 1
        assert game_identity_count == 1
        assert team_identity_count == 2
        assert len(observations) == 2
        assert observations[0].status == "scheduled"
        assert observations[0].home_score is None
        assert observations[0].away_score is None
        assert observations[1].status == "final"
        assert observations[1].home_score == 111
        assert observations[1].away_score == 108
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_observation_timestamp_is_idempotent() -> None:
    engine = create_database_engine(_settings_or_skip())
    session_factory = create_session_factory(engine)
    store = StructuredSportsStore()
    observed_at = datetime.now(timezone.utc)

    try:
        async with session_factory() as session:
            session.add(_provider_source())
            await session.commit()

        async with session_factory() as session:
            first = await store.store_thesportsdb_event(
                session,
                _event(idEvent=str(uuid4())),
                observed_at=observed_at,
            )
            second = await store.store_thesportsdb_event(
                session,
                _event(idEvent=(
                    await session.scalar(
                        select(SportsExternalIdentityRecord.external_id)
                        .where(
                            SportsExternalIdentityRecord.provider_key
                            == "thesportsdb",
                            SportsExternalIdentityRecord.entity_type == "game",
                        )
                    )
                )),
                observed_at=observed_at,
            )
            await session.commit()

            assert first.id == second.id
            count = await session.scalar(
                select(func.count())
                .select_from(GameObservationRecord)
                .where(GameObservationRecord.id == first.id)
            )
            assert count == 1
    finally:
        await engine.dispose()
