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
            with pytest.raises(ValueError, match="collision"):
                await SqlAlchemyRankingStore(session).archive(replace(early, value=4.0))
    finally:
        await engine.dispose()
