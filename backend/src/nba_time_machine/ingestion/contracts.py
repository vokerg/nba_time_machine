from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool


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


class VerificationStatus(StrEnum):
    DISCOVERY_REQUIRED = "discovery_required"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str = Field(min_length=1)
    kind: SourceKind
    adapter: str = Field(min_length=1, max_length=96)
    category: list[str] = Field(default_factory=list)
    locator: str = Field(min_length=1)
    enabled: StrictBool = False
    verification_status: VerificationStatus
    cadence_minutes: int = Field(gt=0)
    requires_auth: StrictBool = False
    retention_policy: RetentionPolicy
    adapter_settings: dict[str, Any] = Field(default_factory=dict)


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
