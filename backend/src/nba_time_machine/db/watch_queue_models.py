"""Queue membership stores only personal intent, never outcome-derived data."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUIDType
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base

class WatchQueueRecord(Base):
    __tablename__ = "watch_queue"
    __table_args__ = (
        CheckConstraint("queue_state IN ('queued','done','dismissed')", name="queue_state_valid"),
        Index("ix_watch_queue_profile_added", "profile_id", "added_at", "game_id"),
    )
    profile_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("timeline_states.profile_id", ondelete="CASCADE"), primary_key=True)
    game_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)
    queue_state: Mapped[str] = mapped_column(String(16), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
