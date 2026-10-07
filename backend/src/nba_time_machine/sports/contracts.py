from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedProviderTeam:
    external_id: str
    name: str


@dataclass(frozen=True, slots=True)
class NormalizedGameObservation:
    external_event_id: str
    season_label: str
    home_team: NormalizedProviderTeam
    away_team: NormalizedProviderTeam
    status: str
    scheduled_tip_at: datetime | None
    home_score: int | None
    away_score: int | None
    metadata: dict[str, Any] = field(default_factory=dict)
