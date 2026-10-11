"""Explicit, transactional materialization of trusted historical ranking evidence.

This is an internal write path, NOT an HTTP read, disclosure, or recommendation
endpoint. The caller owns the database transaction. Missing evidence never
produces a guessed score or a new archive row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from nba_time_machine.ranking.scoring import (
    POSTGAME_VERSION, PREGAME_VERSION, ScoreKind, VersionedScore,
    score_evidence_is_consistent,
)


class RankingEvidenceReader(Protocol):
    async def pregame(self, game_id: UUID, *, as_of: datetime) -> VersionedScore | None: ...
    async def postgame(self, game_id: UUID, *, as_of: datetime) -> VersionedScore | None: ...


class RankingArchiveWriter(Protocol):
    async def archive(self, score: VersionedScore) -> object: ...


class RankingMaterializationService:
    """Bind trusted as-of evidence extraction to the append-only score archive.

    No implicit present-time, caller-provided evidence, fallback score or
    public response is allowed. True means a score was archived (or matched an
    identical prior snapshot); False means there was no trusted evidence.
    """

    def __init__(self, evidence: RankingEvidenceReader, archive: RankingArchiveWriter) -> None:
        self._evidence = evidence
        self._archive = archive

    async def materialize(
        self, game_id: UUID, *, kind: ScoreKind, as_of: datetime,
    ) -> bool:
        if type(game_id) is not UUID:
            raise ValueError("a canonical game UUID is required")
        if type(kind) is not ScoreKind:
            raise ValueError("a typed pregame or postgame score kind is required")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        cursor = as_of.astimezone(timezone.utc)

        if kind is ScoreKind.PREGAME:
            score = await self._evidence.pregame(game_id, as_of=cursor)
            version = PREGAME_VERSION
        else:
            score = await self._evidence.postgame(game_id, as_of=cursor)
            version = POSTGAME_VERSION

        if score is None:
            return False
        # Defense in depth: reject accidentally cross-wired or future evidence
        # rather than persisting it as if it belonged to the requested snapshot.
        if (
            type(score) is not VersionedScore
            or score.game_id != game_id
            or score.kind is not kind
            or score.model_version != version
            or score.as_of != cursor
            or any(
                part.available_at > cursor or part.observed_at > cursor
                for part in score.components
            )
        ):
            raise ValueError("trusted ranking reader returned inconsistent evidence")

        await self._archive.archive(score)
        return True
