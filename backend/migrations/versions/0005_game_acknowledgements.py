"""Persist explicit game acknowledgement separately from the global cursor.

Revision ID: 0005_game_acknowledgements
Revises: 0004_timeline_state
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_game_acknowledgements"
down_revision: str | None = "0004_timeline_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_acknowledgements",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["timeline_states.profile_id"],
            name="fk_game_acknowledgements_profile_id_timeline_states",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"],
            name="fk_game_acknowledgements_game_id_games",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "game_id", name="pk_game_acknowledgements"
        ),
    )
    op.create_index(
        "ix_game_acknowledgements_game_id", "game_acknowledgements", ["game_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_game_acknowledgements_game_id", table_name="game_acknowledgements")
    op.drop_table("game_acknowledgements")
