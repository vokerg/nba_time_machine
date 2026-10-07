from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID as UUIDType
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class SourceRecord(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("cadence_minutes > 0", name="cadence_minutes_positive"),
        CheckConstraint(
            "retention_policy IN "
            "('full', 'normalized_full', 'metadata_excerpt', 'metadata_only')",
            name="retention_policy_valid",
        ),
        Index("ix_sources_enabled_kind", "enabled", "kind"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    verification_status: Mapped[str] = mapped_column(String(64), nullable=False)
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_auth: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    retention_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    runtime_cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CollectionRunRecord(Base):
    __tablename__ = "collection_runs"

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    collector_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class SourceItemRecord(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "canonical_identity",
            name="uq_source_items_source_identity",
        ),
        Index("ix_source_items_source_available", "source_id", "available_at"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_identity: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    item_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class SourceOutcomeRecord(Base):
    __tablename__ = "source_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "collection_run_id",
            "source_id",
            name="uq_source_outcomes_run_source",
        ),
        CheckConstraint(
            "status IN "
            "('ok', 'idle', 'skipped_config', 'rate_limited', 'auth_error', "
            "'blocked', 'parse_error', 'network_error', 'partial')",
            name="status_valid",
        ),
        CheckConstraint("items_seen >= 0", name="items_seen_nonnegative"),
        CheckConstraint("captures_written >= 0", name="captures_written_nonnegative"),
        Index("ix_source_outcomes_source", "source_id"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    collection_run_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    items_seen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    captures_written: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    outcome_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class RawCaptureRecord(Base):
    __tablename__ = "raw_captures"
    __table_args__ = (
        UniqueConstraint(
            "collection_run_id",
            "source_id",
            "external_id",
            "content_hash",
            name="uq_raw_captures_run_source_external_hash",
        ),
        Index("ix_raw_captures_source_captured", "source_id", "captured_at"),
        Index("ix_raw_captures_source_item", "source_item_id"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    collection_run_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_item_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    capture_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class SeasonRecord(Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("league", "label", name="uq_seasons_league_label"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    starts_on: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TeamRecord(Base):
    __tablename__ = "teams"
    __table_args__ = (
        Index("ix_teams_league_abbreviation", "league", "abbreviation"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PlayerRecord(Base):
    __tablename__ = "players"

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class GameRecord(Base):
    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint("home_team_id <> away_team_id", name="different_teams"),
        Index("ix_games_season", "season_id"),
        Index("ix_games_home_team", "home_team_id"),
        Index("ix_games_away_team", "away_team_id"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    season_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("seasons.id", ondelete="RESTRICT"),
        nullable=False,
    )
    home_team_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"),
        nullable=False,
    )
    away_team_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"),
        nullable=False,
    )
    game_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SportsExternalIdentityRecord(Base):
    __tablename__ = "sports_external_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider_key",
            "entity_type",
            "external_id",
            name="uq_sports_external_identity_provider_type_external",
        ),
        CheckConstraint(
            "num_nonnulls(season_id, team_id, player_id, game_id) = 1",
            name="one_target",
        ),
        CheckConstraint(
            "(entity_type = 'season' AND season_id IS NOT NULL) OR "
            "(entity_type = 'team' AND team_id IS NOT NULL) OR "
            "(entity_type = 'player' AND player_id IS NOT NULL) OR "
            "(entity_type = 'game' AND game_id IS NOT NULL)",
            name="target_matches_type",
        ),
        Index("ix_sports_external_identity_season", "season_id"),
        Index("ix_sports_external_identity_team", "team_id"),
        Index("ix_sports_external_identity_player", "player_id"),
        Index("ix_sports_external_identity_game", "game_id"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    provider_key: Mapped[str] = mapped_column(String(96), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(192), nullable=False)
    season_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"),
        nullable=True,
    )
    team_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
    )
    player_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=True,
    )
    game_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=True,
    )
    identity_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class GameObservationRecord(Base):
    __tablename__ = "game_observations"
    __table_args__ = (
        UniqueConstraint(
            "game_id",
            "source_id",
            "observed_at",
            name="uq_game_observations_game_source_observed",
        ),
        CheckConstraint(
            "status IN "
            "('scheduled', 'in_progress', 'final', 'postponed', 'canceled', 'suspended')",
            name="status_valid",
        ),
        CheckConstraint(
            "home_score IS NULL OR home_score >= 0",
            name="home_score_nonnegative",
        ),
        CheckConstraint(
            "away_score IS NULL OR away_score >= 0",
            name="away_score_nonnegative",
        ),
        Index("ix_game_observations_game_observed", "game_id", "observed_at"),
        Index("ix_game_observations_available", "available_at"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    game_id: Mapped[UUIDType] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_tip_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    actual_tip_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    final_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observation_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class TemporalFactRecord(Base):
    __tablename__ = "temporal_facts"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(season_id, team_id, player_id, game_id) = 1",
            name="one_subject",
        ),
        CheckConstraint(
            "(subject_type = 'season' AND season_id IS NOT NULL) OR "
            "(subject_type = 'team' AND team_id IS NOT NULL) OR "
            "(subject_type = 'player' AND player_id IS NOT NULL) OR "
            "(subject_type = 'game' AND game_id IS NOT NULL)",
            name="subject_matches_type",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="valid_interval_ordered",
        ),
        Index("ix_temporal_facts_season_type_valid", "season_id", "fact_type", "valid_from"),
        Index("ix_temporal_facts_team_type_valid", "team_id", "fact_type", "valid_from"),
        Index("ix_temporal_facts_player_type_valid", "player_id", "fact_type", "valid_from"),
        Index("ix_temporal_facts_game_type_valid", "game_id", "fact_type", "valid_from"),
        Index("ix_temporal_facts_available", "available_at"),
    )

    id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    season_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"),
        nullable=True,
    )
    team_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
    )
    player_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=True,
    )
    game_id: Mapped[UUIDType | None] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=True,
    )
    fact_type: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    fact_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
