"""Trusted historical NBA slate selection and safe profile-scoped list assembly.

Membership is determined ONLY by pre-tip observations already known at the
persisted time cursor. Current/final game rows are never used to select a slate.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.api.read_models import GameListResponse, game_card_from_projection
from nba_time_machine.db import GameObservationRecord, GameRecord, SeasonRecord
from nba_time_machine.spoilers.policy import (
    DisclosureLayer, GameContext, game_is_unsealed, order_game_cards, project_game,
)
from nba_time_machine.spoilers.service import (
    GameAcknowledgementRepository, GameSnapshotRepository, TrustedGameSnapshot,
)
from nba_time_machine.temporal.timeline import TimelineService

_NBA_CLOCK = ZoneInfo("America/New_York")


def nba_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Half-open NBA/Eastern calendar day; each midnight has its own UTC offset."""
    start = datetime.combine(day, time.min, tzinfo=_NBA_CLOCK)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=_NBA_CLOCK)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


class GameSlateRepository(Protocol):
    async def game_ids_on_date(
        self, *, slate_date: date, time_cursor: datetime,
    ) -> tuple[UUID, ...]: ...


class SqlAlchemyGameSlateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def game_ids_on_date(
        self, *, slate_date: date, time_cursor: datetime,
    ) -> tuple[UUID, ...]:
        """Pick each game's LAST historically knowable pre-tip observation.

        Rank first, THEN filter by the observation's tip date and scheduled
        status. Otherwise a changed schedule could place one game on two dates,
        or an older scheduled snapshot could survive a known cancellation.
        """
        if time_cursor.tzinfo is None or time_cursor.utcoffset() is None:
            raise ValueError("time_cursor must be timezone-aware")
        begin, end = nba_day_bounds(slate_date)
        o = GameObservationRecord
        ranked = (
            select(
                o.game_id.label("game_id"),
                o.scheduled_tip_at.label("scheduled_tip_at"),
                o.status.label("status"),
                func.row_number().over(
                    partition_by=o.game_id,
                    order_by=(o.observed_at.desc(), o.id.desc()),
                ).label("position"),
            )
            .join(GameRecord, GameRecord.id == o.game_id)
            .join(SeasonRecord, SeasonRecord.id == GameRecord.season_id)
            .where(
                SeasonRecord.league == "NBA",
                o.scheduled_tip_at.is_not(None),
                o.available_at <= time_cursor,
                o.observed_at <= time_cursor,
                o.available_at < o.scheduled_tip_at,
                o.observed_at < o.scheduled_tip_at,
            )
            .subquery()
        )
        rows = await self._session.scalars(
            select(ranked.c.game_id)
            .where(
                ranked.c.position == 1,
                ranked.c.status == "scheduled",
                ranked.c.scheduled_tip_at >= begin,
                ranked.c.scheduled_tip_at < end,
            )
            .order_by(ranked.c.scheduled_tip_at, ranked.c.game_id)
        )
        return tuple(rows.all())


class GameListService:
    def __init__(
        self,
        timeline: TimelineService,
        slates: GameSlateRepository,
        games: GameSnapshotRepository,
        acknowledgements: GameAcknowledgementRepository,
    ) -> None:
        self._timeline = timeline
        self._slates = slates
        self._games = games
        self._acknowledgements = acknowledgements

    async def list_games(self, profile_id: UUID, *, slate_date: date) -> GameListResponse:
        timeline = await self._timeline.resume(profile_id)
        cursor = timeline.time_cursor
        candidates = await self._slates.game_ids_on_date(
            slate_date=slate_date, time_cursor=cursor,
        )
        projections = []
        states: dict[UUID, str] = {}
        seen: set[UUID] = set()
        begin, end = nba_day_bounds(slate_date)
        for game_id in candidates:
            if game_id in seen:
                continue
            seen.add(game_id)
            snapshot = await self._games.get(game_id, time_cursor=cursor)
            if type(snapshot) is not TrustedGameSnapshot or snapshot.game_id != game_id:
                continue  # A missing or invalid trusted snapshot cannot create a card.
            tip = snapshot.tip_at
            if tip is None or tip.tzinfo is None or tip.utcoffset() is None:
                continue
            if not begin <= tip.astimezone(timezone.utc) < end:
                continue  # Guard against disagreement with the date selector.
            acknowledged = await self._acknowledgements.is_acknowledged(profile_id, game_id)
            context = GameContext(
                game_id=game_id,
                time_cursor=cursor,
                tip_at=tip,
                protection_ends_at=snapshot.protection_ends_at,
                acknowledged=acknowledged,
            )
            projection = project_game(context, DisclosureLayer.PREGAME, snapshot.fields)
            # Missing pre-tip identity or schedule: don't invent an apparent game.
            if not all(
                isinstance(projection.fields.get(key), str) and projection.fields[key].strip()
                for key in ("home_team", "away_team", "scheduled_tip")
            ):
                continue
            projections.append(projection)
            states[game_id] = "acknowledged" if game_is_unsealed(context) else "sealed"
        ordered = order_game_cards(tuple(projections))
        return GameListResponse(
            time_cursor=cursor,
            games=tuple(
                game_card_from_projection(projection, state=states[projection.game_id])
                for projection in ordered
            ),
        )
