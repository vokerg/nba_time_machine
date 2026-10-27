"""Internal append-only SQLAlchemy score archive. No public read serializer here."""
from __future__ import annotations

from datetime import timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db.ranking_models import RecommendationScoreRecord
from nba_time_machine.ranking.scoring import VersionedScore, score_evidence_is_consistent


def _components(score: VersionedScore) -> list[dict[str, object]]:
    return [
        {
            "signal": part.signal,
            "normalized_value": part.normalized_value,
            "weight": part.weight,
            "weighted_contribution": part.weighted_contribution,
            "source_ref": part.source_ref,
            "available_at": part.available_at.astimezone(timezone.utc).isoformat(),
            "observed_at": part.observed_at.astimezone(timezone.utc).isoformat(),
        }
        for part in score.components
    ]


class SqlAlchemyRankingStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def archive(self, score: VersionedScore, *, inspection: dict | None = None) -> RecommendationScoreRecord:
        """Idempotent on equal evidence; reject revision collisions, never overwrite.

        A re-computation with changed inputs must use a new model version or
        a new historical as-of snapshot; changing the old row destroys history.
        """
        if type(score) is not VersionedScore:
            raise TypeError("only a typed VersionedScore may be archived")
        # Validate BEFORE encoding JSON or looking up existing rows. Direct store
        # callers must not bypass the materialization service's evidence guard.
        if not score_evidence_is_consistent(score):
            raise ValueError("cannot archive inconsistent ranking evidence")
        evidence = _components(score)
        as_of = score.as_of.astimezone(timezone.utc)
        current = await self._session.scalar(
            select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == score.game_id,
                RecommendationScoreRecord.score_kind == score.kind.value,
                RecommendationScoreRecord.model_version == score.model_version,
                RecommendationScoreRecord.as_of == as_of,
            )
        )
        if current is not None:
            if (current.score_value != Decimal(str(score.value))
                    or current.components != evidence):
                raise ValueError("ranking revision collision; preserve the original score")
            return current
        record = RecommendationScoreRecord(
            game_id=score.game_id,
            score_kind=score.kind.value,
            model_version=score.model_version,
            as_of=as_of,
            score_value=Decimal(str(score.value)),
            components=evidence,
            inspection=inspection,
        )
        self._session.add(record)
        await self._session.flush()
        return record
