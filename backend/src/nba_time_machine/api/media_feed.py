"""Profile cursor-bound, strict general News/Buzz feed."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.api.read_models import MediaFeedResponse
from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.spoilers.media_feed import MediaFeedService
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineNotInitializedError, TimelineService

router = APIRouter(prefix="/profiles/{profile_id}/media", tags=["media"])


async def get_media_service(request: Request) -> AsyncIterator[tuple[TimelineService, MediaFeedService]]:
    factory = _session_factory(request)
    async with factory() as session:
        yield (
            TimelineService(SqlAlchemyTimelineRepository(session)),
            MediaFeedService(session),
        )


@router.get("", response_model=MediaFeedResponse)
async def list_media(
    profile_id: UUID,
    time_cursor: datetime = Query(...),
    limit: int = Query(10, ge=1, le=25),
    page: str | None = Query(None, max_length=512),
    services: tuple[TimelineService, MediaFeedService] = Depends(get_media_service),
) -> MediaFeedResponse:
    if time_cursor.tzinfo is None or time_cursor.utcoffset() is None:
        raise HTTPException(422, "time_cursor must be timezone-aware")
    expected = time_cursor.astimezone(timezone.utc)
    timeline, media = services
    try:
        saved = await timeline.resume(profile_id)
    except TimelineNotInitializedError as exc:
        raise HTTPException(404, "timeline is not initialized") from exc
    if saved.time_cursor != expected:
        raise HTTPException(409, "saved timeline changed; reload before requesting media")
    try:
        result = await media.list_items(profile_id, cursor=expected, limit=limit, page=page)
    except ValueError as exc:
        raise HTTPException(422, "invalid or stale page token") from exc
    # Fail closed if a concurrent tab advanced the cursor during the query.
    fresh = await timeline.resume(profile_id)
    if fresh.time_cursor != expected:
        raise HTTPException(409, "saved timeline changed; reload before requesting media")
    return result
