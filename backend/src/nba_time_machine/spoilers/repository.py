"""Database adapter for explicit game acknowledgements.

The composite primary key and ON CONFLICT guard make repeated requests
idempotent, including concurrent requests handled by separate processes.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db.acknowledgement_models import GameAcknowledgementRecord


class SqlAlchemyGameAcknowledgementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_acknowledged(self, profile_id: UUID, game_id: UUID) -> bool:
        record = await self._session.scalar(
            select(GameAcknowledgementRecord.profile_id).where(
                GameAcknowledgementRecord.profile_id == profile_id,
                GameAcknowledgementRecord.game_id == game_id,
            )
        )
        return record is not None

    async def acknowledge(self, profile_id: UUID, game_id: UUID) -> None:
        statement = (
            insert(GameAcknowledgementRecord)
            .values(profile_id=profile_id, game_id=game_id)
            .on_conflict_do_nothing(
                index_elements=[
                    GameAcknowledgementRecord.profile_id,
                    GameAcknowledgementRecord.game_id,
                ]
            )
        )
        await self._session.execute(statement)
        await self._session.commit()
