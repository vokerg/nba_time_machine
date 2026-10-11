"""End-to-end PostgreSQL exercise of evidence -> score -> append-only archive."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, RecommendationScoreRecord,
    SeasonRecord, SourceRecord, TeamRecord, TemporalFactRecord,
    create_database_engine, create_session_factory,
)
from nba_time_machine.ranking.evidence import SqlAlchemyRankingEvidenceRepository
from nba_time_machine.ranking.materialize import RankingMaterializationService
from nba_time_machine.ranking.repository import SqlAlchemyRankingStore
from nba_time_machine.ranking.scoring import ScoreKind

TIP = datetime(2026, 5, 5, 1, tzinfo=timezone.utc)
BEFORE = TIP - timedelta(hours=2)
FINAL = TIP + timedelta(hours=3)
AFTER = FINAL + timedelta(minutes=20)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_materialization_uses_only_historical_trusted_fact_and_is_idempotent():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    game_id, season_id, home_id, away_id = (uuid4() for _ in range(4))
    source_id = f"ranking-materialize-{uuid4()}"

    def runner(session):
        return RankingMaterializationService(
            SqlAlchemyRankingEvidenceRepository(session),
            SqlAlchemyRankingStore(session),
        )

    def fact(kind, signal, amount, moment):
        return TemporalFactRecord(
            subject_type="game", game_id=game_id,
            fact_type=f"ranking.{kind}.{signal}",
            value={"normalized_value": amount}, source_id=source_id,
            observed_at=moment, available_at=moment,
            valid_from=TIP - timedelta(days=1), valid_to=None,
        )

    try:
        async with factory.begin() as session:
            session.add_all([
                SourceRecord(
                    id=source_id, name="Ranking archive fixture", kind="structured",
                    adapter="fixture", category=[],
                    locator="https://example.invalid/ranking-materialize",
                    enabled=False, verification_status="verified", cadence_minutes=10,
                    requires_auth=False, retention_policy="metadata_only",
                ),
                SeasonRecord(id=season_id, league="NBA", label=str(season_id)),
                TeamRecord(id=home_id, league="NBA", name="Materialize Home"),
                TeamRecord(id=away_id, league="NBA", name="Materialize Away"),
            ])
            await session.flush()
            session.add(GameRecord(
                id=game_id, season_id=season_id,
                home_team_id=home_id, away_team_id=away_id,
            ))
            await session.flush()
            session.add_all([
                GameObservationRecord(
                    game_id=game_id, source_id=source_id, status="scheduled",
                    scheduled_tip_at=TIP, observed_at=BEFORE - timedelta(minutes=15),
                    available_at=BEFORE - timedelta(minutes=15),
                ),
                fact("pregame", "expected_closeness", 0.4, BEFORE - timedelta(minutes=5)),
                # A postgame feature without an actual trusted final is unusable.
                fact("postgame", "comeback", 1.0, BEFORE - timedelta(minutes=5)),
            ])

        async with factory.begin() as session:
            service = runner(session)
            assert await service.materialize(game_id, kind=ScoreKind.PREGAME, as_of=BEFORE)
            assert await service.materialize(game_id, kind=ScoreKind.PREGAME, as_of=BEFORE)
            assert not await service.materialize(game_id, kind=ScoreKind.POSTGAME, as_of=BEFORE)

        async with factory() as session:
            rows = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game_id,
            ))).all()
            assert len(rows) == 1
            assert rows[0].score_kind == "pregame"
            assert float(rows[0].score_value) == 4.0
            assert rows[0].components[0]["source_ref"].startswith(
                f"temporal_fact:{source_id}:"
            )

        async with factory.begin() as session:
            session.add_all([
                GameObservationRecord(
                    game_id=game_id, source_id=source_id, status="final",
                    scheduled_tip_at=TIP, final_at=FINAL,
                    observed_at=AFTER - timedelta(minutes=10),
                    available_at=AFTER - timedelta(minutes=10),
                ),
                fact("postgame", "comeback", 1.0, AFTER - timedelta(minutes=5)),
            ])

        async with factory.begin() as session:
            service = runner(session)
            assert await service.materialize(game_id, kind=ScoreKind.POSTGAME, as_of=AFTER)
            # The historical pre-tip snapshot remains archived, not overwritten.
            assert not await service.materialize(game_id, kind=ScoreKind.PREGAME, as_of=AFTER)

        async with factory() as session:
            rows = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game_id,
            ))).all()
            assert len(rows) == 2
            assert {row.score_kind for row in rows} == {"pregame", "postgame"}
            post = next(row for row in rows if row.score_kind == "postgame")
            assert float(post.score_value) == 10.0
            assert post.components[0]["observed_at"] == (
                AFTER - timedelta(minutes=5)
            ).isoformat()
    finally:
        await engine.dispose()
