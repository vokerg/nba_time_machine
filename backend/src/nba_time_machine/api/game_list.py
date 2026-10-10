"""Profile-scoped historical slate. Only a calendar date is client-supplied."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from nba_time_machine.api.read_models import GameListResponse
from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.spoilers.game_list import GameListService, SqlAlchemyGameSlateRepository
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.temporal import (
    SqlAlchemyTimelineRepository, TimelineNotInitializedError, TimelineService,
)

router = APIRouter(prefix="/profiles/{profile_id}/games", tags=["game-list"])


async def get_game_list_service(request: Request) -> AsyncIterator[GameListService]:
    factory = _session_factory(request)
    async with factory() as session:
        yield GameListService(
            TimelineService(SqlAlchemyTimelineRepository(session)),
            SqlAlchemyGameSlateRepository(session),
            SqlAlchemyGameSnapshotRepository(session),
            SqlAlchemyGameAcknowledgementRepository(session),
        )


@router.get("", response_model=GameListResponse)
async def list_historical_games(
    profile_id: UUID,
    slate_date: date = Query(..., alias="date"),
    service: GameListService = Depends(get_game_list_service),
) -> GameListResponse:
    try:
        return await service.list_games(profile_id, slate_date=slate_date)
    except TimelineNotInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
