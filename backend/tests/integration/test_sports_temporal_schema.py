from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nba_time_machine.db import (
    DatabaseSettings,
    GameObservationRecord,
    GameRecord,
    SeasonRecord,
    SourceRecord,
    SportsExternalIdentityRecord,
    TeamRecord,
    TemporalFactRecord,
    create_database_engine,
    create_session_factory,
)


def _database_settings_or_skip() -> DatabaseSettings:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


def _source(source_id: str) -> SourceRecord:
    return SourceRecord(
        id=source_id,
        name="Sports schema test source",
        kind="structured",
        adapter="nba_structured",
        category=["test"],
        locator="https://example.test/sports",
        enabled=False,
        verification_status="unverified",
        cadence_minutes=10,
        requires_auth=False,
        retention_policy="normalized_full",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provider_external_identity_is_unique_per_entity_type() -> None:
    engine = create_database_engine(_database_settings_or_skip())
    session_factory = create_session_factory(engine)

    first_team_id = uuid4()
    second_team_id = uuid4()

    try:
        async with session_factory() as session:
            session.add_all(
                [
                    TeamRecord(
                        id=first_team_id,
                        league="NBA",
                        name="First Team",
                        abbreviation="ONE",
                    ),
                    TeamRecord(
                        id=second_team_id,
                        league="NBA",
                        name="Second Team",
                        abbreviation="TWO",
                    ),
                ]
            )
            await session.flush()
            session.add(
                SportsExternalIdentityRecord(
                    id=uuid4(),
                    provider_key="provider-a",
                    entity_type="team",
                    external_id="team-42",
                    team_id=first_team_id,
                )
            )
            await session.commit()

        async with session_factory() as session:
            session.add(
                SportsExternalIdentityRecord(
                    id=uuid4(),
                    provider_key="provider-a",
                    entity_type="team",
                    external_id="team-42",
                    team_id=second_team_id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()

        async with session_factory() as session:
            session.add(
                SportsExternalIdentityRecord(
                    id=uuid4(),
                    provider_key="provider-b",
                    entity_type="game",
                    external_id="bad-target",
                    team_id=first_team_id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_final_game_observation_does_not_overwrite_pregame_state() -> None:
    engine = create_database_engine(_database_settings_or_skip())
    session_factory = create_session_factory(engine)

    source_id = f"sports-source-{uuid4()}"
    season_id = uuid4()
    home_team_id = uuid4()
    away_team_id = uuid4()
    game_id = uuid4()

    observed_pregame_at = datetime.now(timezone.utc) - timedelta(hours=5)
    scheduled_tip_at = observed_pregame_at + timedelta(hours=2)
    observed_final_at = scheduled_tip_at + timedelta(hours=3)

    try:
        async with session_factory() as session:
            session.add_all(
                [
                    _source(source_id),
                    SeasonRecord(
                        id=season_id,
                        league="NBA",
                        label=f"test-{uuid4()}",
                    ),
                    TeamRecord(
                        id=home_team_id,
                        league="NBA",
                        name="Home Team",
                        abbreviation="HME",
                    ),
                    TeamRecord(
                        id=away_team_id,
                        league="NBA",
                        name="Away Team",
                        abbreviation="AWY",
                    ),
                ]
            )
            await session.flush()
            session.add(
                GameRecord(
                    id=game_id,
                    season_id=season_id,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    game_type="regular_season",
                )
            )
            await session.flush()
            session.add(
                GameObservationRecord(
                    id=uuid4(),
                    game_id=game_id,
                    source_id=source_id,
                    observed_at=observed_pregame_at,
                    available_at=observed_pregame_at,
                    status="scheduled",
                    scheduled_tip_at=scheduled_tip_at,
                )
            )
            await session.commit()

        async with session_factory() as session:
            session.add(
                GameObservationRecord(
                    id=uuid4(),
                    game_id=game_id,
                    source_id=source_id,
                    observed_at=observed_final_at,
                    available_at=observed_final_at,
                    status="final",
                    scheduled_tip_at=scheduled_tip_at,
                    actual_tip_at=scheduled_tip_at + timedelta(minutes=4),
                    final_at=observed_final_at,
                    home_score=111,
                    away_score=108,
                )
            )
            await session.commit()

        async with session_factory() as session:
            observations = (
                await session.scalars(
                    select(GameObservationRecord)
                    .where(GameObservationRecord.game_id == game_id)
                    .order_by(GameObservationRecord.observed_at)
                )
            ).all()

        assert len(observations) == 2
        assert observations[0].status == "scheduled"
        assert observations[0].scheduled_tip_at == scheduled_tip_at
        assert observations[0].home_score is None
        assert observations[0].away_score is None
        assert observations[1].status == "final"
        assert observations[1].home_score == 111
        assert observations[1].away_score == 108
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_temporal_fact_versions_preserve_validity_history() -> None:
    engine = create_database_engine(_database_settings_or_skip())
    session_factory = create_session_factory(engine)

    source_id = f"fact-source-{uuid4()}"
    team_id = uuid4()
    first_valid_from = datetime.now(timezone.utc) - timedelta(days=2)
    second_valid_from = first_valid_from + timedelta(days=1)

    try:
        async with session_factory() as session:
            session.add_all(
                [
                    _source(source_id),
                    TeamRecord(
                        id=team_id,
                        league="NBA",
                        name="Fact Team",
                        abbreviation="FCT",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    TemporalFactRecord(
                        id=uuid4(),
                        subject_type="team",
                        team_id=team_id,
                        fact_type="standings.record",
                        value={"wins": 10, "losses": 5},
                        source_id=source_id,
                        valid_from=first_valid_from,
                        valid_to=second_valid_from,
                        observed_at=first_valid_from,
                        available_at=first_valid_from,
                    ),
                    TemporalFactRecord(
                        id=uuid4(),
                        subject_type="team",
                        team_id=team_id,
                        fact_type="standings.record",
                        value={"wins": 11, "losses": 5},
                        source_id=source_id,
                        valid_from=second_valid_from,
                        valid_to=None,
                        observed_at=second_valid_from,
                        available_at=second_valid_from,
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            facts = (
                await session.scalars(
                    select(TemporalFactRecord)
                    .where(
                        TemporalFactRecord.team_id == team_id,
                        TemporalFactRecord.fact_type == "standings.record",
                    )
                    .order_by(TemporalFactRecord.valid_from)
                )
            ).all()

        assert len(facts) == 2
        assert facts[0].value == {"wins": 10, "losses": 5}
        assert facts[0].valid_to == second_valid_from
        assert facts[1].value == {"wins": 11, "losses": 5}
        assert facts[1].valid_to is None

        async with session_factory() as session:
            session.add(
                TemporalFactRecord(
                    id=uuid4(),
                    subject_type="team",
                    team_id=team_id,
                    fact_type="standings.record",
                    value={"wins": 12, "losses": 5},
                    source_id=source_id,
                    valid_from=second_valid_from,
                    valid_to=second_valid_from,
                    observed_at=second_valid_from,
                    available_at=second_valid_from,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
