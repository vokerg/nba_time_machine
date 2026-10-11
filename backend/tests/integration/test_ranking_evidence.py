"""PostgreSQL regression for trusted as-of ranking feature selection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, SeasonRecord,
    SourceRecord, TeamRecord, TemporalFactRecord, create_database_engine,
    create_session_factory,
)
from nba_time_machine.ranking.evidence import SqlAlchemyRankingEvidenceRepository

TIP = datetime(2026, 5, 5, 1, tzinfo=timezone.utc)
EARLY = TIP - timedelta(hours=3)
FINAL = TIP + timedelta(hours=3)
SOURCE_ID = "ranking-evidence-fixture"
ALT_SOURCE_ID = "ranking-evidence-alternate"


async def _source(session, source_id=SOURCE_ID):
    if await session.get(SourceRecord, source_id) is None:
        session.add(SourceRecord(
            id=source_id, name="Ranking fixture", kind="structured",
            adapter="fixture", category=[], locator=f"https://example.invalid/{source_id}",
            enabled=False, verification_status="verified", cadence_minutes=10,
            requires_auth=False, retention_policy="metadata_only",
        ))
        await session.flush()


async def _game(session, *, league="NBA"):
    season_id, home_id, away_id, game_id = (uuid4() for _ in range(4))
    session.add_all([
        SeasonRecord(id=season_id, league=league, label=str(season_id)),
        TeamRecord(id=home_id, league=league, name="Fixture Home"),
        TeamRecord(id=away_id, league=league, name="Fixture Away"),
    ])
    await session.flush()
    session.add(GameRecord(
        id=game_id, season_id=season_id,
        home_team_id=home_id, away_team_id=away_id,
    ))
    await session.flush()
    return game_id


def _observation(game_id, *, at, status="scheduled", final_at=None,
                 source_id=SOURCE_ID, available=None):
    return GameObservationRecord(
        game_id=game_id, source_id=source_id, observed_at=at,
        available_at=available or at,
        status=status, scheduled_tip_at=TIP, final_at=final_at,
    )


def _fact(game_id, kind, signal, value, *, at, available=None,
          source_id=SOURCE_ID):
    return TemporalFactRecord(
        subject_type="game", game_id=game_id,
        fact_type=f"ranking.{kind}.{signal}", value=value,
        source_id=source_id,
        valid_from=TIP - timedelta(days=1), valid_to=None,
        observed_at=at, available_at=available or at,
    )


def _settings_or_skip():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pregame_uses_historical_known_revision_and_masks_invalid_updates():
    engine = create_database_engine(_settings_or_skip())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await _source(session)
            game_id = await _game(session)
            first = _fact(
                game_id, "pregame", "expected_closeness",
                {"normalized_value": 0.4}, at=EARLY - timedelta(minutes=10),
            )
            backfill = _fact(
                game_id, "pregame", "expected_closeness",
                {"normalized_value": 0.95}, at=EARLY + timedelta(minutes=30),
                available=EARLY - timedelta(minutes=15),
            )
            session.add_all([
                _observation(game_id, at=EARLY - timedelta(minutes=20)),
                first, backfill,
            ])
            await session.commit()

        async with factory() as session:
            repo = SqlAlchemyRankingEvidenceRepository(session)
            historic = await repo.pregame(game_id, as_of=EARLY)
            assert historic is not None
            assert historic.value == 4
            assert historic.components[0].source_ref.endswith(str(first.id))
            later = await repo.pregame(game_id, as_of=EARLY + timedelta(minutes=45))
            assert later is not None and later.value == 9.5
            assert later.components[0].observed_at == backfill.observed_at
            assert await repo.postgame(game_id, as_of=EARLY) is None
            assert await repo.pregame(game_id, as_of=TIP) is None
            with pytest.raises(ValueError, match="timezone-aware"):
                await repo.pregame(game_id, as_of=datetime(2026, 5, 4, 21))

        async with factory() as session:
            session.add(_fact(
                game_id, "pregame", "expected_closeness",
                {"normalized_value": True},
                at=EARLY + timedelta(minutes=60),
            ))
            await session.commit()

        async with factory() as session:
            repo = SqlAlchemyRankingEvidenceRepository(session)
            # A malformed newer fact must not resurrect a stale older one.
            assert await repo.pregame(game_id, as_of=EARLY + timedelta(minutes=70)) is None
            session.add(_observation(
                game_id, at=EARLY + timedelta(minutes=75), status="postponed",
            ))
            await session.flush()
            assert await repo.pregame(game_id, as_of=EARLY + timedelta(minutes=90)) is None
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgame_requires_trusted_final_and_postfinal_fact_provenance():
    engine = create_database_engine(_settings_or_skip())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await _source(session)
            game_id = await _game(session)
            session.add_all([
                _observation(game_id, at=EARLY),
                _observation(
                    game_id, at=FINAL + timedelta(minutes=10),
                    status="final", final_at=FINAL,
                ),
                _fact(game_id, "postgame", "overtime",
                      {"normalized_value": 1.0}, at=EARLY),
                _fact(game_id, "postgame", "clutch",
                      {"normalized_value": 0.9}, at=FINAL + timedelta(minutes=20)),
                _fact(game_id, "postgame", "comeback",
                      {"normalized_value": 0.6}, at=FINAL + timedelta(minutes=50)),
                _fact(game_id, "pregame", "expected_closeness",
                      {"normalized_value": 0.2}, at=EARLY),
            ])
            await session.commit()

        async with factory() as session:
            repo = SqlAlchemyRankingEvidenceRepository(session)
            assert await repo.postgame(game_id, as_of=FINAL) is None
            score = await repo.postgame(game_id, as_of=FINAL + timedelta(minutes=30))
            assert score is not None and score.kind.value == "postgame"
            assert score.value == 9
            assert [c.signal for c in score.components] == ["clutch"]
            assert await repo.pregame(game_id, as_of=FINAL + timedelta(minutes=30)) is None
            updated = await repo.postgame(game_id, as_of=FINAL + timedelta(hours=1))
            assert updated is not None and len(updated.components) == 2
            assert {c.signal for c in updated.components} == {"clutch", "comeback"}

        async with factory() as session:
            # A later provider 'final' without a trusted final_at cannot
            # reuse the previous score or infer an end time from collection.
            session.add(_observation(
                game_id, at=FINAL + timedelta(hours=2),
                status="final", final_at=None,
            ))
            await session.commit()
        async with factory() as session:
            assert await SqlAlchemyRankingEvidenceRepository(session).postgame(
                game_id, as_of=FINAL + timedelta(hours=3),
            ) is None
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_nba_games_and_unknown_game_facts_fail_closed():
    engine = create_database_engine(_settings_or_skip())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await _source(session)
            game_id = await _game(session, league="WNBA")
            session.add_all([
                _observation(game_id, at=EARLY),
                _fact(game_id, "pregame", "rivalry",
                      {"normalized_value": 1.0}, at=EARLY),
            ])
            await session.commit()
        async with factory() as session:
            repo = SqlAlchemyRankingEvidenceRepository(session)
            assert await repo.pregame(game_id, as_of=EARLY) is None
            assert await repo.pregame(uuid4(), as_of=EARLY) is None
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_equal_time_conflicts_fail_closed_without_uuid_tiebreakers():
    engine = create_database_engine(_settings_or_skip())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await _source(session)
            await _source(session, ALT_SOURCE_ID)
            ambiguous_game = await _game(session)
            ambiguous_feature_game = await _game(session)
            later_available_game = await _game(session)
            session.add_all([
                _observation(ambiguous_game, at=EARLY),
                _observation(ambiguous_game, at=EARLY, status="postponed",
                             source_id=ALT_SOURCE_ID),
                _fact(ambiguous_game, "pregame", "rivalry",
                      {"normalized_value": 0.8}, at=EARLY),
                _observation(ambiguous_feature_game, at=EARLY),
                _fact(ambiguous_feature_game, "pregame", "expected_closeness",
                      {"normalized_value": 0.2}, at=EARLY),
                _fact(ambiguous_feature_game, "pregame", "expected_closeness",
                      {"normalized_value": 0.9}, at=EARLY,
                      source_id=ALT_SOURCE_ID),
                _fact(ambiguous_feature_game, "pregame", "rivalry",
                      {"normalized_value": 0.6}, at=EARLY),
                _observation(later_available_game, at=EARLY),
                _observation(later_available_game, at=EARLY,
                             status="postponed", source_id=ALT_SOURCE_ID,
                             available=EARLY + timedelta(minutes=5)),
                _fact(later_available_game, "pregame", "rivalry",
                      {"normalized_value": 0.5}, at=EARLY),
            ])
            await session.commit()

        async with factory() as session:
            repo = SqlAlchemyRankingEvidenceRepository(session)
            # Exact tied observation timestamps cannot be resolved by UUID.
            assert await repo.pregame(ambiguous_game, as_of=EARLY) is None

            # One ambiguous feature does not prevent an independently
            # sourced, unambiguous signal from producing a partial score.
            partial = await repo.pregame(ambiguous_feature_game, as_of=EARLY)
            assert partial is not None and partial.value == 6
            assert [c.signal for c in partial.components] == ["rivalry"]

            # A later-available correction with the same observed_at is
            # selected only after its availability, not by a random UUID.
            assert await repo.pregame(later_available_game, as_of=EARLY) is not None
            assert await repo.pregame(
                later_available_game, as_of=EARLY + timedelta(minutes=10),
            ) is None
    finally:
        await engine.dispose()
