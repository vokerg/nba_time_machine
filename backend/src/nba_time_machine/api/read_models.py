"""Strict, sparse HTTP response contracts over the trusted spoiler-policy projections.

These are serialization contracts, not authorization. Build projections with the
policy engine first; #14 will supply persisted timeline/acknowledgement state.
Never construct these responses from provider rows, raw media, or AI output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, FiniteFloat, field_validator, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from nba_time_machine.spoilers.policy import (
    DisclosureLayer,
    GameProjection,
    MediaProjection,
)

_PREGAME = frozenset({
    "home_team", "away_team", "scheduled_tip", "pregame_interest",
    "pregame_standings", "pregame_availability",
})
_CARD = frozenset({"home_team", "away_team", "scheduled_tip", "pregame_interest"})
_VERDICT = _PREGAME | {"watchability_verdict"}
_WHY = _VERDICT | {"watchability_reason"}
_FULL = _WHY | {
    "in_game_status", "home_score", "away_score", "result", "box_score",
    "recap", "highlight_url", "highlight_thumbnail", "highlight_runtime_seconds",
}
_MEDIA = frozenset({"headline", "excerpt", "thumbnail_url", "runtime_seconds"})


class _SafeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_serializer(mode="wrap")
    def omit_absent_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """An unavailable field is absent on the wire, not null or CSS-hidden."""
        return {name: value for name, value in handler(self).items() if value is not None}


class GameCardResponse(_SafeResponse):
    game_id: UUID
    state: Literal["sealed", "acknowledged"]
    disclosure: Literal["pregame"] = "pregame"
    home_team: str | None = None
    away_team: str | None = None
    scheduled_tip: str | None = None
    pregame_interest: FiniteFloat | None = None


class PregameDetailResponse(GameCardResponse):
    pregame_standings: str | None = None
    pregame_availability: str | None = None


class WatchabilityResponse(_SafeResponse):
    game_id: UUID
    disclosure: Literal["watchability"] = "watchability"
    watchability_verdict: str | None = None


class WatchabilityReasonResponse(WatchabilityResponse):
    disclosure: Literal["why"] = "why"
    watchability_reason: str | None = None


class FullGameResponse(_SafeResponse):
    """Only constructed from the policy's FULL projection, never an input flag."""

    game_id: UUID
    disclosure: Literal["full"] = "full"
    home_team: str | None = None
    away_team: str | None = None
    scheduled_tip: str | None = None
    pregame_interest: FiniteFloat | None = None
    pregame_standings: str | None = None
    pregame_availability: str | None = None
    watchability_verdict: str | None = None
    watchability_reason: str | None = None
    in_game_status: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    result: str | None = None
    box_score: str | None = None
    recap: str | None = None
    highlight_url: str | None = None
    highlight_thumbnail: str | None = None
    highlight_runtime_seconds: int | None = None


class MediaFeedItemResponse(_SafeResponse):
    item_id: str
    headline: str
    excerpt: str | None = None
    thumbnail_url: str | None = None
    runtime_seconds: int | None = None


class _TimelineResponse(_SafeResponse):
    time_cursor: datetime

    @field_validator("time_cursor")
    @classmethod
    def normalize_cursor(cls, cursor: datetime) -> datetime:
        if cursor.tzinfo is None or cursor.utcoffset() is None:
            raise ValueError("time_cursor must be timezone-aware")
        return cursor.astimezone(timezone.utc)


class GameListResponse(_TimelineResponse):
    """Composable dashboard game endpoint; order must be spoiler-safe upstream."""

    games: tuple[GameCardResponse, ...]


class MediaFeedResponse(_TimelineResponse):
    """General feed; never expands when a single game is acknowledged."""

    items: tuple[MediaFeedItemResponse, ...]


def _game_fields(projection: GameProjection, layer: DisclosureLayer, allowed: frozenset[str]) -> dict[str, object]:
    if type(projection) is not GameProjection:
        raise TypeError("a policy GameProjection is required")
    if projection.disclosure is not layer:
        raise ValueError(f"expected policy disclosure {layer.name}")
    if not isinstance(projection.fields, dict):
        raise TypeError("policy fields must be a mapping")
    unknown = set(projection.fields) - allowed
    if unknown:
        raise ValueError(f"unexpected fields in {layer.name} projection: {sorted(unknown)}")
    return projection.fields


def game_card_from_projection(
    projection: GameProjection, *, state: Literal["sealed", "acknowledged"]
) -> GameCardResponse:
    fields = _game_fields(projection, DisclosureLayer.PREGAME, _PREGAME)
    return GameCardResponse(
        game_id=projection.game_id, state=state,
        **{name: value for name, value in fields.items() if name in _CARD},
    )


def pregame_detail_from_projection(
    projection: GameProjection, *, state: Literal["sealed", "acknowledged"]
) -> PregameDetailResponse:
    fields = _game_fields(projection, DisclosureLayer.PREGAME, _PREGAME)
    return PregameDetailResponse(game_id=projection.game_id, state=state, **fields)


def watchability_from_projection(projection: GameProjection) -> WatchabilityResponse:
    fields = _game_fields(projection, DisclosureLayer.WATCHABILITY, _VERDICT)
    return WatchabilityResponse(
        game_id=projection.game_id,
        **{name: value for name, value in fields.items() if name == "watchability_verdict"},
    )


def reason_from_projection(projection: GameProjection) -> WatchabilityReasonResponse:
    fields = _game_fields(projection, DisclosureLayer.WHY, _WHY)
    return WatchabilityReasonResponse(
        game_id=projection.game_id,
        **{name: value for name, value in fields.items()
           if name in ("watchability_verdict", "watchability_reason")},
    )


def full_game_from_projection(projection: GameProjection) -> FullGameResponse:
    fields = _game_fields(projection, DisclosureLayer.FULL, _FULL)
    return FullGameResponse(game_id=projection.game_id, **fields)


def media_item_from_projection(projection: MediaProjection) -> MediaFeedItemResponse:
    if type(projection) is not MediaProjection:
        raise TypeError("a policy MediaProjection is required")
    if not isinstance(projection.fields, dict) or set(projection.fields) - _MEDIA:
        raise ValueError("unexpected fields in media projection")
    return MediaFeedItemResponse(item_id=projection.item_id, **projection.fields)
