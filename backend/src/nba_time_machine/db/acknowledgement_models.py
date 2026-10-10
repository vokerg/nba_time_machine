"""Durable explicit per-game reveals; never a record of 'watched' status."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class GameAcknowledgementRecord(Base):
    __tablename__ = "game_acknowledgements"
    __table_args__ = (Index("ix_game_acknowledgements_game_id", "game_id"),)

    profile_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timeline_states.profile_id", ondelete="CASCADE"),
        primary_key=True,
    )
    game_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        primary_key=True,
    )
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
