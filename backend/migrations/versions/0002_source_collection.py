"""Add source registry, collection provenance, and capture tables.

Revision ID: 0002_source_collection
Revises: 0001_baseline
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_source_collection"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=96), nullable=False),
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("verification_status", sa.String(length=64), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "requires_auth",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("retention_policy", sa.String(length=32), nullable=False),
        sa.Column(
            "adapter_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "runtime_cursor",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cadence_minutes > 0",
            name="ck_sources_cadence_minutes_positive",
        ),
        sa.CheckConstraint(
            "retention_policy IN "
            "('full', 'normalized_full', 'metadata_excerpt', 'metadata_only')",
            name="ck_sources_retention_policy_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
    )
    op.create_index(
        "ix_sources_enabled_kind",
        "sources",
        ["enabled", "kind"],
        unique=False,
    )

    op.create_table(
        "collection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collector_version", sa.String(length=128), nullable=True),
        sa.Column(
            "run_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_collection_runs"),
    )

    op.create_table(
        "source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("canonical_identity", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "item_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_items_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_items"),
        sa.UniqueConstraint(
            "source_id",
            "canonical_identity",
            name="uq_source_items_source_identity",
        ),
    )
    op.create_index(
        "ix_source_items_source_available",
        "source_items",
        ["source_id", "available_at"],
        unique=False,
    )

    op.create_table(
        "source_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "items_seen",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "captures_written",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN "
            "('ok', 'idle', 'skipped_config', 'rate_limited', 'auth_error', "
            "'blocked', 'parse_error', 'network_error', 'partial')",
            name="ck_source_outcomes_status_valid",
        ),
        sa.CheckConstraint(
            "items_seen >= 0",
            name="ck_source_outcomes_items_seen_nonnegative",
        ),
        sa.CheckConstraint(
            "captures_written >= 0",
            name="ck_source_outcomes_captures_written_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
            name="fk_source_outcomes_collection_run_id_collection_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_outcomes_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_outcomes"),
        sa.UniqueConstraint(
            "collection_run_id",
            "source_id",
            name="uq_source_outcomes_run_source",
        ),
    )
    op.create_index(
        "ix_source_outcomes_source",
        "source_outcomes",
        ["source_id"],
        unique=False,
    )

    op.create_table(
        "raw_captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "capture_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
            name="fk_raw_captures_collection_run_id_collection_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_raw_captures_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"],
            ["source_items.id"],
            name="fk_raw_captures_source_item_id_source_items",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_captures"),
        sa.UniqueConstraint(
            "collection_run_id",
            "source_id",
            "external_id",
            "content_hash",
            name="uq_raw_captures_run_source_external_hash",
        ),
    )
    op.create_index(
        "ix_raw_captures_source_captured",
        "raw_captures",
        ["source_id", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_raw_captures_source_item",
        "raw_captures",
        ["source_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_raw_captures_source_item", table_name="raw_captures")
    op.drop_index("ix_raw_captures_source_captured", table_name="raw_captures")
    op.drop_table("raw_captures")

    op.drop_index("ix_source_outcomes_source", table_name="source_outcomes")
    op.drop_table("source_outcomes")

    op.drop_index("ix_source_items_source_available", table_name="source_items")
    op.drop_table("source_items")

    op.drop_table("collection_runs")

    op.drop_index("ix_sources_enabled_kind", table_name="sources")
    op.drop_table("sources")
