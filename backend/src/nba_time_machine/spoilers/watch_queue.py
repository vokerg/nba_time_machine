"""Personal queue: persisted membership and strictly safe game-card projections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.api.read_models import GameCardResponse, game_card_from_projection
from nba_time_machine.db import GameRecord, SeasonRecord, TimelineStateRecord, WatchQueueRecord
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository
from nba_time_machine.spoilers.policy import DisclosureLayer, GameContext, game_is_unsealed, project_game
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository
from nba_time_machine.spoilers.service import TrustedGameSnapshot

QueueState = Literal["queued", "done", "dismissed"]
QueueView = Literal["pregame", "observed", "replay"]
_NBA_CLOCK = ZoneInfo("America/New_York")


class StaleQueueCursorError(Exception):
    pass


class QueueNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SafeQueueItem:
    game_id: UUID
    queue_state: QueueState
    game: GameCardResponse | None


@dataclass(frozen=True, slots=True)
class SafeQueue:
    time_cursor: datetime
    items: tuple[SafeQueueItem, ...]


def require_cursor(cursor: datetime) -> datetime:
    if cursor.tzinfo is None or cursor.utcoffset() is None:
        raise ValueError("time_cursor must include a timezone")
    return cursor.astimezone(timezone.utc)


class WatchQueueService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _cursor(self, profile_id: UUID, expected: datetime, *, lock: bool = False) -> datetime:
        stmt = select(TimelineStateRecord.time_cursor).where(TimelineStateRecord.profile_id == profile_id)
        if lock:
            stmt = stmt.with_for_update()
        current = await self._session.scalar(stmt)
        if current is None:
            raise QueueNotFoundError("Profile is not initialized.")
        cursor = require_cursor(current)
        if cursor != require_cursor(expected):
            raise StaleQueueCursorError("Timeline changed; reload the queue.")
        return cursor

    async def save(self, profile_id: UUID, game_id: UUID, state: QueueState, *, expected_cursor: datetime) -> None:
        # The timeline row lock serializes queue writes with cursor advancement.
        await self._cursor(profile_id, expected_cursor, lock=True)
        nba_game = await self._session.scalar(
            select(GameRecord.id).join(SeasonRecord, GameRecord.season_id == SeasonRecord.id)
            .where(GameRecord.id == game_id, SeasonRecord.league == "NBA")
        )
        if nba_game is None:
            raise QueueNotFoundError("Game is not available.")
        await self._session.execute(
            insert(WatchQueueRecord)
            .values(profile_id=profile_id, game_id=game_id, queue_state=state)
            .on_conflict_do_update(
                index_elements=[WatchQueueRecord.profile_id, WatchQueueRecord.game_id],
                set_={"queue_state": state, "updated_at": func.now()},
            )
        )
        await self._session.commit()

    async def remove(self, profile_id: UUID, game_id: UUID, *, expected_cursor: datetime) -> None:
        await self._cursor(profile_id, expected_cursor, lock=True)
        await self._session.execute(
            delete(WatchQueueRecord).where(
                WatchQueueRecord.profile_id == profile_id,
                WatchQueueRecord.game_id == game_id,
            )
        )
        await self._session.commit()

    async def list(self, profile_id: UUID, *, expected_cursor: datetime, view: QueueView = "replay") -> SafeQueue:
        cursor = await self._cursor(profile_id, expected_cursor)
        rows = (await self._session.scalars(
            select(WatchQueueRecord)
            .where(WatchQueueRecord.profile_id == profile_id)
            .order_by(WatchQueueRecord.added_at, WatchQueueRecord.game_id)
        )).all()
        reader = SqlAlchemyGameSnapshotRepository(
            self._session, observed_schedule=view == "observed", season_replay=view == "replay",
        )
        acknowledgements = SqlAlchemyGameAcknowledgementRepository(self._session)
        items = []
        for row in rows:
            card = None
            snapshot = await reader.get(row.game_id, time_cursor=cursor)
            if (type(snapshot) is TrustedGameSnapshot and snapshot.game_id == row.game_id
                    and snapshot.tip_at is not None and snapshot.tip_at.tzinfo is not None
                    and snapshot.tip_at.utcoffset() is not None) and (
                view != "replay" or
                snapshot.tip_at.astimezone(_NBA_CLOCK).date() <= cursor.astimezone(_NBA_CLOCK).date()
            ):
                context = GameContext(
                    game_id=row.game_id, time_cursor=cursor,
                    tip_at=snapshot.tip_at, protection_ends_at=snapshot.protection_ends_at,
                    acknowledged=await acknowledgements.is_acknowledged(profile_id, row.game_id),
                    observed_schedule=view == "observed", season_replay=view == "replay",
                )
                projection = project_game(context, DisclosureLayer.PREGAME, snapshot.fields)
                if all(
                    isinstance(projection.fields.get(name), str) and projection.fields[name].strip()
                    for name in ("home_team", "away_team", "scheduled_tip")
                ):
                    card = game_card_from_projection(
                        projection, state="acknowledged" if game_is_unsealed(context) else "sealed",
                    )
            items.append(SafeQueueItem(game_id=row.game_id, queue_state=row.queue_state, game=card))
        # Fail closed if another tab advanced the cursor during the read.
        await self._cursor(profile_id, expected_cursor)
        return SafeQueue(time_cursor=cursor, items=tuple(items))
