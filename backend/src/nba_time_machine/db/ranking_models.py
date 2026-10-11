"""Append-only, versioned snapshots of internally scored games.

Rows contain raw ranking components and are never exposed as API read models.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID as UUIDType
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Numeric, String,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class RecommendationScoreRecord(Base):
    __tablename__ = "recommendation_scores"
    __table_args__ = (
        CheckConstraint(
            "score_kind IN ('pregame', 'postgame')",
            name="valid_score_kind",
        ),
        CheckConstraint("score_value >= 0 AND score_value <= 10", name="score_value_bounded"),
        UniqueConstraint(
            "game_id", "score_kind", "model_version", "as_of",
            name="uq_recommendation_scores_game_kind_version_as_of",
        ),
        Index("ix_recommendation_scores_game_id", "game_id"),
        Index("ix_recommendation_scores_kind_as_of", "score_kind", "as_of"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    game_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
    )
    score_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score_value: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    components: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
