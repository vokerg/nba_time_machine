from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    STRUCTURED = "structured"
    WEB = "web"
    MEDIA = "media"
    DOCUMENT = "document"
    X_ACCOUNT = "x_account"
    PODCAST = "podcast"
    YOUTUBE = "youtube"
    STATS_SITE = "stats_site"


class RetentionPolicy(StrEnum):
    FULL = "full"
    NORMALIZED_FULL = "normalized_full"
    METADATA_EXCERPT = "metadata_excerpt"
    METADATA_ONLY = "metadata_only"


class SourceDefinition(BaseModel):
    id: str
    name: str
    kind: SourceKind
    adapter: str
    category: list[str] = Field(default_factory=list)
    locator: str
    enabled: bool = False
    verification_status: str
    cadence_minutes: int = Field(gt=0)
    requires_auth: bool = False
    retention_policy: RetentionPolicy


class RawCapture(BaseModel):
    source_id: str
    external_id: str | None = None
    canonical_url: str | None = None
    published_at: datetime | None = None
    discovered_at: datetime
    captured_at: datetime
    content_type: str | None = None
    title: str | None = None
    author: str | None = None
    text: str | None = None
    raw_payload: str | None = None
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
