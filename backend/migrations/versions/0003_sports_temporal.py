"""Add sports identity, game observation, and temporal fact tables.

Revision ID: 0003_sports_temporal
Revises: 0002_source_collection
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_sports_temporal"
down_revision = "0002_source_collection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("league", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_seasons"),
        sa.UniqueConstraint("league", "label", name="uq_seasons_league_label"),
    )

    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("league", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("abbreviation", sa.String(length=12), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
    )
    op.create_index(
        "ix_teams_league_abbreviation",
        "teams",
        ["league", "abbreviation"],
        unique=False,
    )

    op.create_table(
        "players",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
    )

    op.create_table(
        "games",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("home_team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("away_team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_type", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_games_different_teams",
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"],
            ["teams.id"],
            name="fk_games_away_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"],
            ["teams.id"],
            name="fk_games_home_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name="fk_games_season_id_seasons",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_games"),
    )
    op.create_index("ix_games_season", "games", ["season_id"], unique=False)
    op.create_index("ix_games_home_team", "games", ["home_team_id"], unique=False)
    op.create_index("ix_games_away_team", "games", ["away_team_id"], unique=False)

    op.create_table(
        "sports_external_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_key", sa.String(length=96), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=192), nullable=False),
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "identity_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(season_id, team_id, player_id, game_id) = 1",
            name="ck_sports_external_identities_one_target",
        ),
        sa.CheckConstraint(
            "(entity_type = 'season' AND season_id IS NOT NULL) OR "
            "(entity_type = 'team' AND team_id IS NOT NULL) OR "
            "(entity_type = 'player' AND player_id IS NOT NULL) OR "
            "(entity_type = 'game' AND game_id IS NOT NULL)",
            name="ck_sports_external_identities_target_matches_type",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name="fk_sports_external_identities_game_id_games",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_sports_external_identities_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name="fk_sports_external_identities_season_id_seasons",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_sports_external_identities_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sports_external_identities"),
        sa.UniqueConstraint(
            "provider_key",
            "entity_type",
            "external_id",
            name="uq_sports_external_identity_provider_type_external",
        ),
    )
    op.create_index(
        "ix_sports_external_identity_season",
        "sports_external_identities",
        ["season_id"],
        unique=False,
    )
    op.create_index(
        "ix_sports_external_identity_team",
        "sports_external_identities",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "ix_sports_external_identity_player",
        "sports_external_identities",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_sports_external_identity_game",
        "sports_external_identities",
        ["game_id"],
        unique=False,
    )

    op.create_table(
        "game_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_tip_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_tip_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column(
            "observation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN "
            "('scheduled', 'in_progress', 'final', 'postponed', 'canceled', 'suspended')",
            name="ck_game_observations_status_valid",
        ),
        sa.CheckConstraint(
            "home_score IS NULL OR home_score >= 0",
            name="ck_game_observations_home_score_nonnegative",
        ),
        sa.CheckConstraint(
            "away_score IS NULL OR away_score >= 0",
            name="ck_game_observations_away_score_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name="fk_game_observations_game_id_games",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_game_observations_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_game_observations"),
        sa.UniqueConstraint(
            "game_id",
            "source_id",
            "observed_at",
            name="uq_game_observations_game_source_observed",
        ),
    )
    op.create_index(
        "ix_game_observations_game_observed",
        "game_observations",
        ["game_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_game_observations_available",
        "game_observations",
        ["available_at"],
        unique=False,
    )

    op.create_table(
        "temporal_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fact_type", sa.String(length=128), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fact_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(season_id, team_id, player_id, game_id) = 1",
            name="ck_temporal_facts_one_subject",
        ),
        sa.CheckConstraint(
            "(subject_type = 'season' AND season_id IS NOT NULL) OR "
            "(subject_type = 'team' AND team_id IS NOT NULL) OR "
            "(subject_type = 'player' AND player_id IS NOT NULL) OR "
            "(subject_type = 'game' AND game_id IS NOT NULL)",
            name="ck_temporal_facts_subject_matches_type",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_temporal_facts_valid_interval_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name="fk_temporal_facts_game_id_games",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_temporal_facts_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name="fk_temporal_facts_season_id_seasons",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_temporal_facts_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_temporal_facts_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_temporal_facts"),
    )
    op.create_index(
        "ix_temporal_facts_season_type_valid",
        "temporal_facts",
        ["season_id", "fact_type", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_temporal_facts_team_type_valid",
        "temporal_facts",
        ["team_id", "fact_type", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_temporal_facts_player_type_valid",
        "temporal_facts",
        ["player_id", "fact_type", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_temporal_facts_game_type_valid",
        "temporal_facts",
        ["game_id", "fact_type", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_temporal_facts_available",
        "temporal_facts",
        ["available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_facts_available", table_name="temporal_facts")
    op.drop_index("ix_temporal_facts_game_type_valid", table_name="temporal_facts")
    op.drop_index("ix_temporal_facts_player_type_valid", table_name="temporal_facts")
    op.drop_index("ix_temporal_facts_team_type_valid", table_name="temporal_facts")
    op.drop_index("ix_temporal_facts_season_type_valid", table_name="temporal_facts")
    op.drop_table("temporal_facts")

    op.drop_index("ix_game_observations_available", table_name="game_observations")
    op.drop_index("ix_game_observations_game_observed", table_name="game_observations")
    op.drop_table("game_observations")

    op.drop_index(
        "ix_sports_external_identity_game",
        table_name="sports_external_identities",
    )
    op.drop_index(
        "ix_sports_external_identity_player",
        table_name="sports_external_identities",
    )
    op.drop_index(
        "ix_sports_external_identity_team",
        table_name="sports_external_identities",
    )
    op.drop_index(
        "ix_sports_external_identity_season",
        table_name="sports_external_identities",
    )
    op.drop_table("sports_external_identities")

    op.drop_index("ix_games_away_team", table_name="games")
    op.drop_index("ix_games_home_team", table_name="games")
    op.drop_index("ix_games_season", table_name="games")
    op.drop_table("games")

    op.drop_table("players")

    op.drop_index("ix_teams_league_abbreviation", table_name="teams")
    op.drop_table("teams")

    op.drop_table("seasons")
