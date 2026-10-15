"""Personal watch queue, independent of game acknowledgements.
Revision ID: 0009_watch_queue
Revises: 0008_source_item_entity_links
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_watch_queue"
down_revision: str | None = "0008_source_item_entity_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "watch_queue",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("queue_state", sa.String(16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("queue_state IN ('queued','done','dismissed')", name="ck_watch_queue_queue_state_valid"),
        sa.ForeignKeyConstraint(["profile_id"], ["timeline_states.profile_id"], name="fk_watch_queue_profile_id_timeline_states", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], name="fk_watch_queue_game_id_games", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "game_id", name="pk_watch_queue"),
    )
    op.create_index("ix_watch_queue_profile_added", "watch_queue", ["profile_id", "added_at", "game_id"])

def downgrade() -> None:
    op.drop_index("ix_watch_queue_profile_added", table_name="watch_queue")
    op.drop_table("watch_queue")
