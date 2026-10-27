"""Persist admin breakdowns with explicitly published ratings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_saved_rating_details"
down_revision = "0010_media_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recommendation_scores", sa.Column("inspection", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("recommendation_scores", "inspection")
