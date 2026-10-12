"""Append-only, untrusted observations linking collected items to sports entities."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class SourceItemEntityLinkRecord(Base):
    """A candidate association, not permission to reveal an item or a game."""

    __tablename__ = "source_item_entity_links"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(game_id, team_id, player_id) = 1",
            name="one_target",
        ),
        CheckConstraint(
            "(entity_type = 'game' AND game_id IS NOT NULL) OR "
            "(entity_type = 'team' AND team_id IS NOT NULL) OR "
            "(entity_type = 'player' AND player_id IS NOT NULL)",
            name="target_matches_type",
        ),
        CheckConstraint(
            "link_state IN ('present', 'retracted')",
            name="link_state_valid",
        ),
        CheckConstraint(
            "derivation_method IN ('manual', 'rule', 'model')",
            name="derivation_method_valid",
        ),
        CheckConstraint(
            "available_at >= observed_at",
            name="availability_not_backdated",
        ),
        Index(
            "uq_source_item_entity_links_game_observation",
            "source_item_id", "game_id", "observed_at",
            unique=True,
            postgresql_where=text("game_id IS NOT NULL"),
        ),
        Index(
            "uq_source_item_entity_links_team_observation",
            "source_item_id", "team_id", "observed_at",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
        Index(
            "uq_source_item_entity_links_player_observation",
            "source_item_id", "player_id", "observed_at",
            unique=True,
            postgresql_where=text("player_id IS NOT NULL"),
        ),
        Index("ix_source_item_entity_links_available", "available_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    game_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=True,
    )
    team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True,
    )
    player_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("players.id", ondelete="RESTRICT"), nullable=True,
    )
    link_state: Mapped[str] = mapped_column(String(16), nullable=False)
    derivation_method: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
