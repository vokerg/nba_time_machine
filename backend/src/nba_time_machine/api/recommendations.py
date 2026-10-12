"""POST-only opt-in for outcome-influenced recommendations.

The request may choose candidate UUIDs and uniform viewing-time allocation,
but never supplies ranking scores, historical evidence, or spoiler state.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.ranking.service import (
    OutcomeRankingConsentRequired, RecommendationSlateUnavailable,
    RecommendationTimelineChanged, WatchabilityRecommendationService,
)
from nba_time_machine.spoilers.game_list import GameListService, SqlAlchemyGameSlateRepository
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.temporal import (
    SqlAlchemyTimelineRepository, TimelineNotInitializedError, TimelineService,
)

router = APIRouter(
    prefix="/profiles/{profile_id}/recommendations", tags=["recommendations"],
)


class WatchabilityRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slate_date: date
    candidate_game_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    consent_to_outcome_ranking: bool = Field(default=False, strict=True)
    budget_minutes: int | None = Field(default=None, ge=0, le=1440, strict=True)
    planned_minutes_per_game: int = Field(default=120, ge=1, le=720, strict=True)

    @model_validator(mode="after")
    def require_distinct_game_ids(self) -> "WatchabilityRecommendationRequest":
        if len(set(self.candidate_game_ids)) != len(self.candidate_game_ids):
            raise ValueError("candidate_game_ids must be unique")
        return self


class WatchabilityRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_ids: tuple[UUID, ...]


async def get_watchability_recommendation_service(
    request: Request,
) -> AsyncIterator[WatchabilityRecommendationService]:
    factory = _session_factory(request)
    async with factory() as session:
        timeline = TimelineService(SqlAlchemyTimelineRepository(session))
        yield WatchabilityRecommendationService(
            timeline,
            SqlAlchemyPostgameScoreRepository(session),
            GameListService(
                timeline,
                SqlAlchemyGameSlateRepository(session),
                SqlAlchemyGameSnapshotRepository(session),
                SqlAlchemyGameAcknowledgementRepository(session),
            ),
        )


@router.post("/watchability", response_model=WatchabilityRecommendationResponse)
async def recommend_watchability(
    profile_id: UUID,
    body: WatchabilityRecommendationRequest,
    service: WatchabilityRecommendationService = Depends(
        get_watchability_recommendation_service
    ),
) -> WatchabilityRecommendationResponse:
    try:
        ids = await service.recommend(
            profile_id,
            body.candidate_game_ids,
            slate_date=body.slate_date,
            consent_to_outcome_ranking=body.consent_to_outcome_ranking,
            budget_minutes=body.budget_minutes,
            planned_minutes_per_game=body.planned_minutes_per_game,
        )
    except OutcomeRankingConsentRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc),
        ) from exc
    except TimelineNotInitializedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc
    except RecommendationSlateUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc),
        ) from exc
    except RecommendationTimelineChanged as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc),
        ) from exc
    return WatchabilityRecommendationResponse(game_ids=ids)
