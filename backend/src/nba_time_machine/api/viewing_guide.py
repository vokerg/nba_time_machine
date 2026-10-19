"""Explicit two-mode API, with bounded date-scoped spoiler consent."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, AwareDatetime, StrictBool

from nba_time_machine.api.game_list import game_list_response
from nba_time_machine.api.timeline import _session_factory
from nba_time_machine.ranking.config import RankingDisclosureSettings
from nba_time_machine.ranking.evidence import SqlAlchemyRankingEvidenceRepository
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.spoilers.game_list import SqlAlchemyGameSlateRepository
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.spoilers.viewing_guide import ViewingGuideService
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService, TimelineNotInitializedError

router = APIRouter(prefix="/profiles/{profile_id}/guide", tags=["viewing-guide"])
Mode = Literal["browse", "time-machine"]


async def get_viewing_guide(request: Request):
    async with _session_factory(request)() as session:
        async def verify(gid, cutoff):
            result = await MorningRankingPipeline(session).derive(gid, as_of=cutoff)
            if result is not None:
                return result[2]
            return await SqlAlchemyRankingEvidenceRepository(session).postgame(gid, as_of=cutoff)
        yield ViewingGuideService(
            TimelineService(SqlAlchemyTimelineRepository(session)),
            SqlAlchemyGameSlateRepository(session, observed_schedule=True),
            SqlAlchemyGameSnapshotRepository(session, observed_schedule=True, knowledge_bounded=True),
            SqlAlchemyGameAcknowledgementRepository(session),
            SqlAlchemyPostgameScoreRepository(session), verify, RankingDisclosureSettings().bands())


class DisclosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    mode: Mode
    time_cursor: AwareDatetime
    level: Literal["verdict", "clue", "rating", "full", "order"]
    consent: StrictBool = False
    game_id: UUID | None = None


@router.get("")
async def games(profile_id: UUID, date: date, mode: Mode = "browse", service=Depends(get_viewing_guide)):
    try:
        state, cutoff, slate = await service.list_games(profile_id, date, mode)
        response = game_list_response(slate).model_dump(mode="json")
        response["time_cursor"] = state.time_cursor
        # Card state must not reveal whether the game has finished.
        for card in response["games"]:
            card["state"] = "sealed"
        return response
    except TimelineNotInitializedError as exc:
        raise HTTPException(404, "Initialize profile first") from exc
    except RuntimeError as exc:
        raise HTTPException(409, "Refresh the selected date") from exc


@router.post("/disclose")
async def disclose(profile_id: UUID, body: DisclosureRequest, service=Depends(get_viewing_guide)):
    if body.consent is not True:
        raise HTTPException(403, "Explicit spoiler consent required")
    if body.level == "order" and body.game_id is not None:
        raise HTTPException(422, "Watch order is date scoped")
    if body.game_id is None and body.level not in ("order", "full"):
        raise HTTPException(422, "Choose a game for this detail level")
    try:
        return await service.disclose(profile_id, body.date, body.mode, body.time_cursor, body.level, body.game_id)
    except TimelineNotInitializedError as exc:
        raise HTTPException(404, "Initialize profile first") from exc
    except PermissionError as exc:
        raise HTTPException(403, "Game is outside selected date") from exc
    except RuntimeError as exc:
        raise HTTPException(409, "Timeline changed; refresh") from exc
