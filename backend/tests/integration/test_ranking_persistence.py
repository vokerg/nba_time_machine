"""PostgreSQL checks for append-only scoring snapshots and raw-score isolation."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from nba_time_machine.db import (
    DatabaseSettings, GameRecord, RecommendationScoreRecord, SeasonRecord,
    TeamRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.ranking import (
    FeatureObservation, PostgameSignal, PregameSignal,
    score_postgame, score_pregame,
)
from nba_time_machine.ranking.repository import SqlAlchemyRankingStore

TIP = datetime(2026, 5, 5, 1, tzinfo=timezone.utc)
BEFORE = TIP - timedelta(hours=2)
FINAL = TIP + timedelta(hours=3)
AFTER = FINAL + timedelta(minutes=20)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persist_score_versions_without_overwriting_or_mixing_kinds() -> None:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    game_id, season_id, home_id, away_id = uuid4(), uuid4(), uuid4(), uuid4()
    early = score_pregame(
        game_id, {PregameSignal.RIVALRY: FeatureObservation(.1, "official:pregame", BEFORE, BEFORE)},
        tip_at=TIP, as_of=BEFORE,
    )
    late = score_postgame(
        game_id, {PostgameSignal.COMEBACK: FeatureObservation(1.0, "official:final", AFTER, AFTER)},
        final_at=FINAL, as_of=AFTER,
    )

    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season_id, league="NBA", label="ranking-test"),
                TeamRecord(id=home_id, league="NBA", name="Rank Home"),
                TeamRecord(id=away_id, league="NBA", name="Rank Away"),
            ])
            await session.flush()
            session.add(GameRecord(
                id=game_id, season_id=season_id,
                home_team_id=home_id, away_team_id=away_id,
            ))
            await session.commit()

        async with factory() as session:
            store = SqlAlchemyRankingStore(session)
            original = await store.archive(early)
            assert (await store.archive(early)).id == original.id
            await store.archive(late)
            await session.commit()

        async with factory() as session:
            rows = (await session.scalars(
                select(RecommendationScoreRecord).where(
                    RecommendationScoreRecord.game_id == game_id,
                )
            )).all()
            assert len(rows) == 2
            by_kind = {row.score_kind: row for row in rows}
            assert by_kind["pregame"].score_value == 1
            assert by_kind["postgame"].score_value == 10
            assert by_kind["pregame"].components[0]["source_ref"] == "official:pregame"
            assert by_kind["postgame"].components[0]["observed_at"] == AFTER.isoformat()
            # A consistent revision at the same archival identity still
            # collides: no overwrite is permitted.
            revised = replace(early, components=(
                replace(early.components[0], source_ref="official:corrected"),
            ))
            with pytest.raises(ValueError, match="collision"):
                await SqlAlchemyRankingStore(session).archive(revised)

            # A new snapshot with inconsistent arithmetic cannot enter the
            # archive even when no previous key exists to collide with.
            invalid = replace(late, as_of=AFTER + timedelta(minutes=1), value=9.0)
            with pytest.raises(ValueError, match="inconsistent ranking evidence"):
                await SqlAlchemyRankingStore(session).archive(invalid)
            persisted = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game_id,
            ))).all()
            assert len(persisted) == 2
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_historical_postgame_reader_uses_latest_cursor_safe_version() -> None:
    """A replay cannot use a future snapshot, wrong kind, or corrupt evidence."""
    from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository

    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    game_id, season_id, home_id, away_id = uuid4(), uuid4(), uuid4(), uuid4()
    future = AFTER + timedelta(hours=2)
    early = score_postgame(
        game_id,
        {PostgameSignal.CLUTCH: FeatureObservation(.2, "official:final", AFTER, AFTER)},
        final_at=FINAL, as_of=AFTER,
    )
    later = score_postgame(
        game_id,
        {PostgameSignal.CLUTCH: FeatureObservation(.9, "official:final", future, future)},
        final_at=FINAL, as_of=future,
    )
    pregame = score_pregame(
        game_id,
        {PregameSignal.RIVALRY: FeatureObservation(.95, "official:preview", BEFORE, BEFORE)},
        tip_at=TIP, as_of=BEFORE,
    )
    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season_id, league="NBA", label="ranking-query-test"),
                TeamRecord(id=home_id, league="NBA", name="Query Home"),
                TeamRecord(id=away_id, league="NBA", name="Query Away"),
            ])
            await session.flush()
            session.add(GameRecord(
                id=game_id, season_id=season_id,
                home_team_id=home_id, away_team_id=away_id,
            ))
            await session.commit()
        async with factory() as session:
            store = SqlAlchemyRankingStore(session)
            await store.archive(pregame)
            await store.archive(early)
            await store.archive(later)
            await session.commit()
        async with factory() as session:
            query = SqlAlchemyPostgameScoreRepository(session)
            assert await query.postgame_scores_as_of((game_id,), as_of=BEFORE) == ()
            at_cursor = await query.postgame_scores_as_of((game_id,), as_of=AFTER)
            assert len(at_cursor) == 1
            assert at_cursor[0].value == early.value
            assert at_cursor[0].components[0].source_ref == "official:final"
            at_future = await query.postgame_scores_as_of((game_id,), as_of=future)
            assert len(at_future) == 1 and at_future[0].value == later.value
            # Even a cursor-available row must be rejected when its stored
            # value no longer equals the weighted source features.
            row = await session.scalar(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game_id,
                RecommendationScoreRecord.score_kind == "postgame",
                RecommendationScoreRecord.as_of == future,
            ))
            assert row is not None
            row.score_value = 10
            await session.flush()
            assert await query.postgame_scores_as_of((game_id,), as_of=future) == ()
            row.score_value = later.value
            row.components = [{**row.components[0], "weight": 99}]
            await session.flush()
            assert await query.postgame_scores_as_of((game_id,), as_of=future) == ()
            row.components = [{
                **row.components[0], "weight": later.components[0].weight,
            }]
            await session.flush()
            assert (await query.postgame_scores_as_of((game_id,), as_of=future))[0].value == later.value

            # Corrupted latest evidence is withheld, not replaced by an older
            # score that could conceal a broken historical archive.
            row = await session.scalar(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game_id,
                RecommendationScoreRecord.score_kind == "postgame",
                RecommendationScoreRecord.as_of == future,
            ))
            assert row is not None
            row.components = [{**row.components[0], "observed_at": (future + timedelta(hours=1)).isoformat()}]
            await session.flush()
            assert await query.postgame_scores_as_of((game_id,), as_of=future) == ()
            await session.rollback()
    finally:
        await engine.dispose()
