"""Append-only versioned pregame/postgame ranking snapshots.

Revision ID: 0006_recommendation_scores
Revises: 0005_game_acknowledgements
Create Date: 2026-10-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_recommendation_scores"
down_revision: str | None = "0005_game_acknowledgements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_kind", sa.String(length=12), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score_value", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "score_kind IN ('pregame', 'postgame')",
            name="ck_recommendation_scores_valid_score_kind",
        ),
        sa.CheckConstraint(
            "score_value >= 0 AND score_value <= 10",
            name="ck_recommendation_scores_score_value_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"],
            name="fk_recommendation_scores_game_id_games", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendation_scores"),
        sa.UniqueConstraint(
            "game_id", "score_kind", "model_version", "as_of",
            name="uq_recommendation_scores_game_kind_version_as_of",
        ),
    )
    op.create_index(
        "ix_recommendation_scores_game_id",
        "recommendation_scores", ["game_id"],
    )
    op.create_index(
        "ix_recommendation_scores_kind_as_of",
        "recommendation_scores", ["score_kind", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_scores_kind_as_of", table_name="recommendation_scores",
    )
    op.drop_index(
        "ix_recommendation_scores_game_id", table_name="recommendation_scores",
    )
    op.drop_table("recommendation_scores")
