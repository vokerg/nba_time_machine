"""Metadata-only audit records for validated AI completions.

Revision ID: 0007_ai_result_metadata
Revises: 0006_recommendation_scores
Create Date: 2026-10-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_ai_result_metadata"
down_revision: str | None = "0006_recommendation_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_result_metadata",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("use_case", sa.String(length=96), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=96), nullable=False),
        sa.Column("schema_version", sa.String(length=96), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(use_case) <> ''", name="ck_ai_result_metadata_use_case_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(model_name) <> ''", name="ck_ai_result_metadata_model_name_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(prompt_version) <> ''",
            name="ck_ai_result_metadata_prompt_version_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(schema_version) <> ''",
            name="ck_ai_result_metadata_schema_version_nonblank",
        ),
        sa.CheckConstraint(
            "num_nonnulls(source_item_id, game_id) <= 1",
            name="ck_ai_result_metadata_at_most_one_subject",
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name="ck_ai_result_metadata_prompt_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name="ck_ai_result_metadata_completion_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "total_tokens >= 0", name="ck_ai_result_metadata_total_tokens_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"], ["source_items.id"],
            name="fk_ai_result_metadata_source_item_id_source_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"],
            name="fk_ai_result_metadata_game_id_games", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_result_metadata"),
    )
    op.create_index(
        "ix_ai_result_metadata_use_case_created",
        "ai_result_metadata", ["use_case", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_result_metadata_use_case_created", table_name="ai_result_metadata",
    )
    op.drop_table("ai_result_metadata")
