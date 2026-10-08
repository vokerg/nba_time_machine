from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUIDType
from uuid import uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class TimelineStateRecord(Base):
    """Persistent forward-only information cursor for one opaque profile."""

    __tablename__ = "timeline_states"

    profile_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    time_cursor: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
