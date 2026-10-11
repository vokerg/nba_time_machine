"""Consent-gated, profile-timeline-scoped internal watchability selection.

Ordering game IDs based on postgame quality is itself an outcome-dependent
spoiler. No caller may activate it by default or by merely reading a GET.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from nba_time_machine.ranking.recommendations import (
    ViewingCandidate, rank_postgame, recommend_for_budget,
)
from nba_time_machine.ranking.scoring import (
    POSTGAME_VERSION, ScoreKind, VersionedScore,
)
from nba_time_machine.temporal.timeline import TimelineService


class OutcomeRankingConsentRequired(PermissionError):
    """Explicit, per-request postgame-ranking opt-in was not supplied."""


class PostgameScoreRepository(Protocol):
    async def postgame_scores_as_of(
        self, game_ids: tuple[UUID, ...], *, as_of: datetime,
    ) -> tuple[VersionedScore, ...]: ...


class WatchabilityRecommendationService:
    def __init__(
        self, timeline: TimelineService, scores: PostgameScoreRepository,
    ) -> None:
        self._timeline = timeline
        self._scores = scores

    async def recommend(
        self,
        profile_id: UUID,
        candidate_game_ids: tuple[UUID, ...],
        *,
        consent_to_outcome_ranking: bool = False,
        budget_minutes: int | None = None,
        planned_minutes_per_game: int = 120,
    ) -> tuple[UUID, ...]:
        """Return IDs only, with an explicit opt-in for ranking-induced spoilers.

        Candidates come from the already-visible pregame slate. The service
        never selects candidates from completed-game state or client scores.
        Planned durations are uniform viewing allocations supplied by the
        user, never actual (potentially spoiler-bearing) game runtime.
        """
        if consent_to_outcome_ranking is not True:
            raise OutcomeRankingConsentRequired("postgame ranking requires explicit consent")
        if (not 1 <= len(candidate_game_ids) <= 32
                or any(type(game_id) is not UUID for game_id in candidate_game_ids)
                or len(set(candidate_game_ids)) != len(candidate_game_ids)):
            raise ValueError("supply 1 to 32 distinct canonical game IDs")
        if budget_minutes is not None and (
            type(budget_minutes) is not int or not 0 <= budget_minutes <= 1440
        ):
            raise ValueError("budget_minutes must be a whole number in [0, 1440]")
        if type(planned_minutes_per_game) is not int or not 1 <= planned_minutes_per_game <= 720:
            raise ValueError("planned_minutes_per_game must be in [1, 720]")

        # Consent is checked BEFORE consulting the profile state or any scores.
        cursor = (await self._timeline.resume(profile_id)).time_cursor
        archived = await self._scores.postgame_scores_as_of(
            candidate_game_ids, as_of=cursor,
        )
        selected: list[VersionedScore] = []
        seen: set[UUID] = set()
        allowed = set(candidate_game_ids)
        for score in archived:
            if (type(score) is not VersionedScore
                    or score.game_id not in allowed or score.game_id in seen
                    or score.kind is not ScoreKind.POSTGAME
                    or score.model_version != POSTGAME_VERSION
                    or score.as_of.tzinfo is None or score.as_of.utcoffset() is None
                    or score.as_of > cursor
                    or not all(
                        component.available_at.tzinfo is not None
                        and component.available_at.utcoffset() is not None
                        and component.observed_at.tzinfo is not None
                        and component.observed_at.utcoffset() is not None
                        and component.available_at <= score.as_of
                        and component.observed_at <= score.as_of
                        and component.source_ref.strip()
                        for component in score.components
                    )):
                continue  # Fail closed on unexpected or future archive evidence.
            seen.add(score.game_id)
            selected.append(score)
        scores = tuple(selected)
        if budget_minutes is None:
            return rank_postgame(scores)
        return recommend_for_budget(
            tuple(ViewingCandidate(score, planned_minutes_per_game) for score in scores),
            budget_minutes=budget_minutes,
        )
