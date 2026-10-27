"""Read only the newest postgame score snapshot available at a profile cursor.

The archived model is an internal-only ranking input. Its raw components,
numeric score and source references are never returned by a public route.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from nba_time_machine.db import RecommendationScoreRecord, TemporalFactRecord, SourceRecord
from nba_time_machine.ranking.scoring import (
    POSTGAME_VERSIONS, OVERALL_VERSION, STAR_OVERALL_VERSION, WATCHABILITY_VERSION, ScoreComponent, ScoreKind, VersionedScore,
    score_evidence_is_consistent,
)


def _score_from_row(row: RecommendationScoreRecord) -> VersionedScore | None:
    """Reject corrupt or future-dated evidence; never try an earlier fallback."""
    try:
        parts = tuple(
            ScoreComponent(
                signal=raw["signal"],
                # Preserve JSON number types for the shared evidence check.
                # Coercing here turns malformed booleans, strings and fractional
                # weights into apparently valid archived ranking evidence.
                normalized_value=raw["normalized_value"],
                weight=raw["weight"],
                weighted_contribution=raw["weighted_contribution"],
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

    async def postgame_scores_as_of(self, game_ids: tuple[UUID, ...], *, as_of: datetime) -> tuple[VersionedScore, ...]:
        rows = await saved_score_rows(self._session, game_ids, as_of=as_of)
        # Publication validates evidence. Reads validate only the saved snapshot.
        return tuple(score for row in rows if (score := _score_from_row(row)) is not None)


async def saved_score_rows(session, game_ids, *, as_of, details=False):
    if not game_ids:
        return []
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("historical ranking read requires an aware cursor")
    r = RecommendationScoreRecord
    latest = (
        select(
            r.id.label("id"),
            func.row_number().over(
                partition_by=r.game_id,
                order_by=(r.as_of.desc(), (r.model_version == WATCHABILITY_VERSION).desc(), (r.model_version == STAR_OVERALL_VERSION).desc(), (r.model_version == OVERALL_VERSION).desc(), r.id.desc()),
            ).label("position"),
        )
        .where(
            r.game_id.in_(game_ids),
            r.score_kind == ScoreKind.POSTGAME.value,
            r.model_version.in_(POSTGAME_VERSIONS),
            r.as_of <= as_of,
        )
        .subquery()
    )
    query = select(r).join(latest, r.id == latest.c.id).where(latest.c.position == 1).order_by(r.game_id)
    if details:
        query = query.options(undefer(r.inspection))
    rows = (await session.scalars(query)).all()
    # Registry access revocation is a permission check, not recalculation.
    # Read IDs/policy columns only; never download or reinterpret source bodies.
    refs = {}
    for row in rows:
        ids = set()
        for part in row.components if isinstance(row.components, list) else ():
            ref = part.get('source_ref', '') if isinstance(part, dict) else ''
            if not isinstance(ref, str):
                continue
            for value in ref.split(':')[1:]:
                try:
                    ids.add(UUID(value))
                except ValueError:
                    pass
        refs[row.id] = ids
    fact_ids = set().union(*refs.values()) if refs else set()
    blocked = set()
    if fact_ids:
        policies = (await session.execute(select(TemporalFactRecord.id, SourceRecord.verification_status,
            SourceRecord.retention_policy).join(SourceRecord, SourceRecord.id == TemporalFactRecord.source_id)
            .where(TemporalFactRecord.id.in_(fact_ids)))).all()
        blocked = {fid for fid, verification, retention in policies
                   if verification != 'verified' or retention not in ('full', 'normalized_full')}
    return [row for row in rows if not refs[row.id] & blocked]
