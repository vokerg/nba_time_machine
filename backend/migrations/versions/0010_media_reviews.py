"""Explicit revision-specific media safety / rights review.

Revision ID: 0010_media_reviews
Revises: 0009_watch_queue
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_media_reviews"
down_revision: str | None = "0009_watch_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_reviews",
        sa.Column("capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sensitivity", sa.String(32), nullable=False),
        sa.Column("game_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("'{}'::uuid[]"), nullable=False),
        sa.Column("rights_cleared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("link_cleared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("sensitivity IN ('general', 'pregame', 'outcome_dependent')", name="ck_media_reviews_sensitivity_valid"),
        sa.CheckConstraint("(sensitivity = 'general' AND cardinality(game_ids) = 0) OR (sensitivity <> 'general' AND cardinality(game_ids) > 0)", name="ck_media_reviews_linkage_valid"),
        sa.ForeignKeyConstraint(["capture_id"], ["raw_captures.id"], name="fk_media_reviews_capture_id_raw_captures", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("capture_id", name="pk_media_reviews"),
    )
    op.create_index("ix_media_reviews_reviewed_at", "media_reviews", ["reviewed_at", "capture_id"])


def downgrade() -> None:
    op.drop_index("ix_media_reviews_reviewed_at", table_name="media_reviews")
    op.drop_table("media_reviews")
