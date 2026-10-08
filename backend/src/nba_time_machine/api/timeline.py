from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nba_time_machine.temporal import (
    SqlAlchemyTimelineRepository,
    TimelineAlreadyInitializedError,
    TimelineNotInitializedError,
    TimelineService,
    TimelineState,
    TimelineWouldMoveBackwardError,
)

router = APIRouter(prefix="/timeline", tags=["timeline"])


class TimelineCursorRequest(BaseModel):
    time_cursor: datetime

    @field_validator("time_cursor")
    @classmethod
    def require_timezone_and_normalize(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("time_cursor must include a timezone offset")
        return value.astimezone(timezone.utc)


class TimelineStateResponse(BaseModel):
    profile_id: UUID
    time_cursor: datetime
    initialized_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, state: TimelineState) -> "TimelineStateResponse":
        return cls(
            profile_id=state.profile_id,
            time_cursor=state.time_cursor,
            initialized_at=state.initialized_at,
            updated_at=state.updated_at,
        )


def _session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )
    return session_factory


async def get_timeline_service(
    request: Request,
) -> AsyncIterator[TimelineService]:
    session_factory = _session_factory(request)
    async with session_factory() as session:
        yield TimelineService(SqlAlchemyTimelineRepository(session))


@router.post(
    "/{profile_id}",
    response_model=TimelineStateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initialize_timeline(
    profile_id: UUID,
    body: TimelineCursorRequest,
    service: TimelineService = Depends(get_timeline_service),
) -> TimelineStateResponse:
    try:
        state = await service.initialize(profile_id, body.time_cursor)
    except TimelineAlreadyInitializedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TimelineStateResponse.from_domain(state)


@router.get(
    "/{profile_id}",
    response_model=TimelineStateResponse,
)
async def get_timeline(
    profile_id: UUID,
    service: TimelineService = Depends(get_timeline_service),
) -> TimelineStateResponse:
    try:
        state = await service.resume(profile_id)
    except TimelineNotInitializedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return TimelineStateResponse.from_domain(state)


@router.put(
    "/{profile_id}",
    response_model=TimelineStateResponse,
)
async def advance_timeline(
    profile_id: UUID,
    body: TimelineCursorRequest,
    service: TimelineService = Depends(get_timeline_service),
) -> TimelineStateResponse:
    try:
        state = await service.advance(profile_id, body.time_cursor)
    except TimelineNotInitializedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except TimelineWouldMoveBackwardError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TimelineStateResponse.from_domain(state)
