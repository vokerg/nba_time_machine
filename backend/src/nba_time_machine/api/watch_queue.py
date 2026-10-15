"""Personal Watch Queue HTTP API; no implicit score, hint or reveal requests."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, field_validator

from nba_time_machine.api.read_models import GameCardResponse
from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.spoilers.watch_queue import (
    QueueNotFoundError, SafeQueue, StaleQueueCursorError, WatchQueueService,
)

router = APIRouter(prefix="/profiles/{profile_id}/watch-queue", tags=["watch-queue"])


class QueueItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    game_id: UUID
    queue_state: Literal["queued", "done", "dismissed"]
    game: GameCardResponse | None


class QueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    time_cursor: datetime
    items: tuple[QueueItemResponse, ...]

    @classmethod
    def from_domain(cls, value: SafeQueue) -> "QueueResponse":
        return cls(
            time_cursor=value.time_cursor,
            items=tuple(QueueItemResponse(
                game_id=item.game_id, queue_state=item.queue_state, game=item.game,
            ) for item in value.items),
        )


class QueueMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    time_cursor: datetime
    queue_state: Literal["queued", "done", "dismissed"]

    @field_validator("time_cursor")
    @classmethod
    def normalize_cursor(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("time_cursor must include a timezone")
        return value.astimezone(timezone.utc)


async def get_queue_service(request: Request) -> AsyncIterator[WatchQueueService]:
    factory = _session_factory(request)
    async with factory() as session:
        yield WatchQueueService(session)


def queue_error(error: Exception) -> HTTPException:
    if isinstance(error, StaleQueueCursorError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, QueueNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=422, detail="Invalid timeline cursor.")


@router.get("", response_model=QueueResponse)
async def list_queue(
    profile_id: UUID,
    time_cursor: datetime = Query(...),
    view: Literal["pregame", "observed", "replay"] = Query("replay"),
    service: WatchQueueService = Depends(get_queue_service),
) -> QueueResponse:
    try:
        return QueueResponse.from_domain(
            await service.list(profile_id, expected_cursor=time_cursor, view=view)
        )
    except (StaleQueueCursorError, QueueNotFoundError, ValueError) as error:
        raise queue_error(error) from error


@router.put("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def save_queue_item(
    profile_id: UUID, game_id: UUID, body: QueueMutationRequest,
    service: WatchQueueService = Depends(get_queue_service),
) -> None:
    try:
        await service.save(profile_id, game_id, body.queue_state, expected_cursor=body.time_cursor)
    except (StaleQueueCursorError, QueueNotFoundError, ValueError) as error:
        raise queue_error(error) from error


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_queue_item(
    profile_id: UUID, game_id: UUID,
    time_cursor: datetime = Query(...),
    service: WatchQueueService = Depends(get_queue_service),
) -> None:
    try:
        await service.remove(profile_id, game_id, expected_cursor=time_cursor)
    except (StaleQueueCursorError, QueueNotFoundError, ValueError) as error:
        raise queue_error(error) from error
