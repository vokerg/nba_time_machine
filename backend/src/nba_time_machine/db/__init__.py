"""Database configuration, models, and session boundaries."""

from .ai_models import AIResultMetadataRecord
from .acknowledgement_models import GameAcknowledgementRecord
from .config import DatabaseNotConfiguredError, DatabaseSettings
from .entity_link_models import SourceItemEntityLinkRecord
from .media_models import MediaReviewRecord
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
from .ranking_models import RecommendationScoreRecord
from .session import create_database_engine, create_session_factory
from .timeline_models import TimelineStateRecord
from .watch_queue_models import WatchQueueRecord

__all__ = [
    "AIResultMetadataRecord",
    "Base",
    "CollectionRunRecord",
    "DatabaseNotConfiguredError",
    "DatabaseSettings",
    "GameAcknowledgementRecord",
    "GameObservationRecord",
    "MediaReviewRecord",
    "GameRecord",
    "PlayerRecord",
    "RawCaptureRecord",
    "RecommendationScoreRecord",
    "SeasonRecord",
    "SourceItemEntityLinkRecord",
    "SourceItemRecord",
    "SourceOutcomeRecord",
    "SourceRecord",
    "SportsExternalIdentityRecord",
    "TeamRecord",
    "TemporalFactRecord",
    "TimelineStateRecord",
    "WatchQueueRecord",
    "create_database_engine",
    "create_session_factory",
]
