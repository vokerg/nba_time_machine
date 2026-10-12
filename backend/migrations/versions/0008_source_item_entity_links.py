"""Append-only candidate sports entity links for normalized source items.

Revision ID: 0008_source_item_entity_links
Revises: 0007_ai_result_metadata
Create Date: 2026-10-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_source_item_entity_links"
down_revision: str | None = "0007_ai_result_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_item_entity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("link_state", sa.String(length=16), nullable=False),
        sa.Column("derivation_method", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(game_id, team_id, player_id) = 1",
            name="ck_source_item_entity_links_one_target",
        ),
        sa.CheckConstraint(
            "(entity_type = 'game' AND game_id IS NOT NULL) OR "
            "(entity_type = 'team' AND team_id IS NOT NULL) OR "
            "(entity_type = 'player' AND player_id IS NOT NULL)",
            name="ck_source_item_entity_links_target_matches_type",
        ),
        sa.CheckConstraint(
            "link_state IN ('present', 'retracted')",
            name="ck_source_item_entity_links_link_state_valid",
        ),
        sa.CheckConstraint(
            "derivation_method IN ('manual', 'rule', 'model')",
            name="ck_source_item_entity_links_derivation_method_valid",
        ),
        sa.CheckConstraint(
            "available_at >= observed_at",
            name="ck_source_item_entity_links_availability_not_backdated",
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"], ["source_items.id"],
            name="fk_source_item_entity_links_source_item_id_source_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"],
            name="fk_source_item_entity_links_game_id_games",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"],
            name="fk_source_item_entity_links_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"],
            name="fk_source_item_entity_links_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_item_entity_links"),
    )
    for target in ("game", "team", "player"):
        op.create_index(
            f"uq_source_item_entity_links_{target}_observation",
            "source_item_entity_links",
            ["source_item_id", f"{target}_id", "observed_at"],
            unique=True,
            postgresql_where=sa.text(f"{target}_id IS NOT NULL"),
        )
    op.create_index(
        "ix_source_item_entity_links_available",
        "source_item_entity_links", ["available_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_item_entity_links_available",
        table_name="source_item_entity_links",
    )
    for target in ("player", "team", "game"):
        op.drop_index(
            f"uq_source_item_entity_links_{target}_observation",
            table_name="source_item_entity_links",
        )
    op.drop_table("source_item_entity_links")
