"""Database configuration, models, and session boundaries."""

from .config import DatabaseNotConfiguredError, DatabaseSettings
from .models import (
    Base,
    CollectionRunRecord,
    GameObservationRecord,
    GameRecord,
    PlayerRecord,
    RawCaptureRecord,
    SeasonRecord,
    SourceItemRecord,
    SourceOutcomeRecord,
    SourceRecord,
    SportsExternalIdentityRecord,
    TeamRecord,
    TemporalFactRecord,
)
from .session import create_database_engine, create_session_factory

__all__ = [
    "Base",
    "CollectionRunRecord",
    "DatabaseNotConfiguredError",
    "DatabaseSettings",
    "GameObservationRecord",
    "GameRecord",
    "PlayerRecord",
    "RawCaptureRecord",
    "SeasonRecord",
    "SourceItemRecord",
    "SourceOutcomeRecord",
    "SourceRecord",
    "SportsExternalIdentityRecord",
    "TeamRecord",
    "TemporalFactRecord",
    "create_database_engine",
    "create_session_factory",
]
