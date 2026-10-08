from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db.timeline_models import TimelineStateRecord

from .timeline import TimelineState


class SqlAlchemyTimelineRepository:
    """PostgreSQL-backed repository with atomic monotonic cursor updates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: UUID) -> TimelineState | None:
        record = await self._session.scalar(
            select(TimelineStateRecord).where(
                TimelineStateRecord.profile_id == profile_id
            )
        )
        return _to_domain(record) if record is not None else None

    async def initialize(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState | None:
        statement = (
            insert(TimelineStateRecord)
            .values(profile_id=profile_id, time_cursor=time_cursor)
            .on_conflict_do_nothing(index_elements=[TimelineStateRecord.profile_id])
            .returning(TimelineStateRecord)
        )
        record = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.commit()
        return _to_domain(record) if record is not None else None

    async def advance_if_not_backward(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState | None:
        statement = (
            update(TimelineStateRecord)
            .where(
                TimelineStateRecord.profile_id == profile_id,
                TimelineStateRecord.time_cursor <= time_cursor,
            )
            .values(
                time_cursor=time_cursor,
                updated_at=func.now(),
            )
            .returning(TimelineStateRecord)
        )
        record = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.commit()
        return _to_domain(record) if record is not None else None


def _to_domain(record: TimelineStateRecord) -> TimelineState:
    return TimelineState(
        profile_id=record.profile_id,
        time_cursor=record.time_cursor,
        initialized_at=record.initialized_at,
        updated_at=record.updated_at,
    )
