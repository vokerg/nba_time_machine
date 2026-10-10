"""HTTP boundary: request only a layer or explicit reveal, never game facts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from nba_time_machine.api.read_models import (
    FullGameResponse,
    PregameDetailResponse,
    WatchabilityReasonResponse,
    WatchabilityResponse,
    full_game_from_projection,
    pregame_detail_from_projection,
    reason_from_projection,
    watchability_from_projection,
)
from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.policy import DisclosureLayer
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.spoilers.service import (
    DisclosedGame,
    GameDisclosureService,
    GameNotFoundError,
    GameResultNotAvailableError,
    SealedGameError,
)
from nba_time_machine.temporal import (
    SqlAlchemyTimelineRepository, TimelineNotInitializedError, TimelineService,
)

router = APIRouter(prefix="/profiles/{profile_id}/games", tags=["game-disclosure"])


async def get_game_disclosure_service(request: Request) -> AsyncIterator[GameDisclosureService]:
    factory = _session_factory(request)
    async with factory() as session:
        yield GameDisclosureService(
            TimelineService(SqlAlchemyTimelineRepository(session)),
            SqlAlchemyGameSnapshotRepository(session),
            SqlAlchemyGameAcknowledgementRepository(session),
        )


async def _disclose(
    service: GameDisclosureService, profile_id: UUID, game_id: UUID,
    layer: DisclosureLayer | None,
) -> DisclosedGame:
    try:
        if layer is None:
            return await service.reveal_full(profile_id, game_id)
        return await service.disclose(profile_id, game_id, layer)
    except (TimelineNotInitializedError, GameNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc
    except (SealedGameError, GameResultNotAvailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc),
        ) from exc


@router.get("/{game_id}/pregame", response_model=PregameDetailResponse)
async def read_pregame(
    profile_id: UUID, game_id: UUID,
    service: GameDisclosureService = Depends(get_game_disclosure_service),
) -> PregameDetailResponse:
    result = await _disclose(service, profile_id, game_id, DisclosureLayer.PREGAME)
    return pregame_detail_from_projection(result.projection, state=result.state)


@router.get("/{game_id}/watchability", response_model=WatchabilityResponse)
async def read_watchability(
    profile_id: UUID, game_id: UUID,
    service: GameDisclosureService = Depends(get_game_disclosure_service),
) -> WatchabilityResponse:
    result = await _disclose(service, profile_id, game_id, DisclosureLayer.WATCHABILITY)
    return watchability_from_projection(result.projection)


@router.get("/{game_id}/why", response_model=WatchabilityReasonResponse)
async def read_why(
    profile_id: UUID, game_id: UUID,
    service: GameDisclosureService = Depends(get_game_disclosure_service),
) -> WatchabilityReasonResponse:
    result = await _disclose(service, profile_id, game_id, DisclosureLayer.WHY)
    return reason_from_projection(result.projection)


@router.get("/{game_id}/full", response_model=FullGameResponse)
async def read_full_if_unsealed(
    profile_id: UUID, game_id: UUID,
    service: GameDisclosureService = Depends(get_game_disclosure_service),
) -> FullGameResponse:
    result = await _disclose(service, profile_id, game_id, DisclosureLayer.FULL)
    return full_game_from_projection(result.projection)


@router.post("/{game_id}/reveal", response_model=FullGameResponse)
async def explicitly_reveal_full(
    profile_id: UUID, game_id: UUID,
    service: GameDisclosureService = Depends(get_game_disclosure_service),
) -> FullGameResponse:
    result = await _disclose(service, profile_id, game_id, None)
    return full_game_from_projection(result.projection)
