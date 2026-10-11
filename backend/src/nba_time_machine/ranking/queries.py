"""Read only the newest postgame score snapshot available at a profile cursor.

The archived model is an internal-only ranking input. Its raw components,
numeric score and source references are never returned by a public route.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db.ranking_models import RecommendationScoreRecord
from nba_time_machine.ranking.scoring import (
    POSTGAME_VERSION, ScoreComponent, ScoreKind, VersionedScore,
    score_evidence_is_consistent,
)


def _score_from_row(row: RecommendationScoreRecord) -> VersionedScore | None:
    """Reject corrupt or future-dated evidence; never try an earlier fallback."""
    try:
        parts = tuple(
            ScoreComponent(
                signal=raw["signal"],
                normalized_value=float(raw["normalized_value"]),
                weight=int(raw["weight"]),
                weighted_contribution=float(raw["weighted_contribution"]),
                source_ref=raw["source_ref"],
                available_at=datetime.fromisoformat(raw["available_at"]),
                observed_at=datetime.fromisoformat(raw["observed_at"]),
            )
            for raw in row.components
        )
        if not parts or any(
            not isinstance(p.source_ref, str) or not p.source_ref.strip()
            or p.available_at.tzinfo is None or p.available_at.utcoffset() is None
            or p.observed_at.tzinfo is None or p.observed_at.utcoffset() is None
            or p.available_at > row.as_of or p.observed_at > row.as_of
            for p in parts
        ):
            return None
        score = VersionedScore(
            game_id=row.game_id,
            kind=ScoreKind(row.score_kind),
            model_version=row.model_version,
            as_of=row.as_of,
            value=float(row.score_value),
            components=parts,
        )
        return score if score_evidence_is_consistent(score) else None
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None


class SqlAlchemyPostgameScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def postgame_scores_as_of(
        self, game_ids: tuple[UUID, ...], *, as_of: datetime,
    ) -> tuple[VersionedScore, ...]:
        if not game_ids:
            return ()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("historical ranking read requires an aware cursor")
        r = RecommendationScoreRecord
        latest = (
            select(
                r.id.label("id"),
                func.row_number().over(
                    partition_by=r.game_id,
                    order_by=(r.as_of.desc(), r.id.desc()),
                ).label("position"),
            )
            .where(
                r.game_id.in_(game_ids),
                r.score_kind == ScoreKind.POSTGAME.value,
                r.model_version == POSTGAME_VERSION,
                r.as_of <= as_of,
            )
            .subquery()
        )
        rows = (await self._session.scalars(
            select(r)
            .join(latest, r.id == latest.c.id)
            .where(latest.c.position == 1)
            .order_by(r.game_id)
        )).all()
        scores = (_score_from_row(row) for row in rows)
        return tuple(score for score in scores if score is not None)
