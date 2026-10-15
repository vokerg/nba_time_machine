"""Explicit per-revision human clearance for general-feed material.

A collector, source item's metadata, or model classification cannot create a
trusted media review. Review rows are inserted only by an audited operator.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class MediaReviewRecord(Base):
    __tablename__ = "media_reviews"
    __table_args__ = (
        Index("ix_media_reviews_reviewed_at", "reviewed_at", "capture_id"),
        CheckConstraint(
            "sensitivity IN ('general', 'pregame', 'outcome_dependent')",
            name="sensitivity_valid",
        ),
        CheckConstraint(
            "(sensitivity = 'general' AND cardinality(game_ids) = 0) OR "
            "(sensitivity <> 'general' AND cardinality(game_ids) > 0)",
            name="linkage_valid",
        ),
    )

    capture_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("raw_captures.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False)
    # Complete association set signed off with this specific capture revision.
    game_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list,
        server_default=text("'{}'::uuid[]"),
    )
    rights_cleared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    link_cleared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
