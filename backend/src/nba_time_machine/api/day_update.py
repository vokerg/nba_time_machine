"""Local-only write action for the unauthenticated personal viewing guide."""
import ipaddress
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict

from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.sports.morning_models import EASTERN
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository, TimelineNotInitializedError

router = APIRouter(prefix="/profiles/{profile_id}/guide/update", tags=["day-update"])


class UpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    time_cursor: AwareDatetime
    mode: Literal["browse"]


def local_access(request):
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    origin = request.headers.get("origin")
    same_origin = not origin or (urlsplit(origin).scheme in ("http", "https")
                                and urlsplit(origin).netloc == request.headers.get("host"))
    if (not local or request.url.hostname not in ("localhost", "127.0.0.1", "::1")
            or not same_origin or request.headers.get("sec-fetch-site") == "cross-site"):
        raise HTTPException(403, "Date updates are local only")


def manager(request):
    jobs = getattr(request.app.state, "day_updates", None)
    if jobs is None:
        raise HTTPException(503, "Date updates unavailable")
    return jobs


@router.post("", status_code=202)
async def start_update(profile_id: UUID, body: UpdateRequest, request: Request, response: Response):
    local_access(request)
    if (request.headers.get("x-guide-action") != "update-day"
            or request.headers.get("content-type", "").split(";")[0] != "application/json"):
        raise HTTPException(403, "Explicit date update required")
    if not date(2025, 7, 1) <= body.date <= min(date(2027, 6, 30), datetime.now(EASTERN).date()):
        raise HTTPException(422, "Choose a supported date up to today")
    async with _session_factory(request)() as session:
        try:
            saved = await TimelineService(SqlAlchemyTimelineRepository(session)).resume(profile_id)
        except TimelineNotInitializedError as exc:
            raise HTTPException(404, "Initialize profile first") from exc
        if saved.time_cursor != body.time_cursor:
            raise HTTPException(409, "Timeline changed; reload saved state")
    try:
        result = manager(request).start(profile_id, body.date)
    except ValueError as exc:
        raise HTTPException(409, "Another date update is running") from exc
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/{job_id}")
async def update_status(profile_id: UUID, job_id: UUID, request: Request, response: Response):
    local_access(request)
    result = manager(request).status(profile_id, job_id)
    if result is None:
        raise HTTPException(404, "Update interrupted or replaced; fetch this date again")
    response.headers["Cache-Control"] = "no-store"
    return result
