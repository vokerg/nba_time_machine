"""Pure spoiler firewall. Callers must only expose its projected output.

No source text is rewritten; ambiguous or unsafely classified input is omitted.
A game acknowledgement is never an exception to the global media time cursor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from math import isfinite
from typing import TypeAlias
from uuid import UUID

Scalar: TypeAlias = str | int | float | bool | None


class DisclosureLayer(IntEnum):
    PREGAME = 0
    WATCHABILITY = 1
    WHY = 2
    FULL = 3


class GameFieldName(str, Enum):
    HOME_TEAM = "home_team"
    AWAY_TEAM = "away_team"
    SCHEDULED_TIP = "scheduled_tip"
    PREGAME_INTEREST = "pregame_interest"
    PREGAME_STANDINGS = "pregame_standings"
    PREGAME_AVAILABILITY = "pregame_availability"
    WATCHABILITY_VERDICT = "watchability_verdict"
    WATCHABILITY_REASON = "watchability_reason"
    IN_GAME_STATUS = "in_game_status"
    HOME_SCORE = "home_score"
    AWAY_SCORE = "away_score"
    RESULT = "result"
    BOX_SCORE = "box_score"
    RECAP = "recap"
    HIGHLIGHT_URL = "highlight_url"
    HIGHLIGHT_THUMBNAIL = "highlight_thumbnail"
    HIGHLIGHT_RUNTIME_SECONDS = "highlight_runtime_seconds"


_FIELD_LAYER: dict[GameFieldName, DisclosureLayer] = {
    **{name: DisclosureLayer.PREGAME for name in (
        GameFieldName.HOME_TEAM,
        GameFieldName.AWAY_TEAM,
        GameFieldName.SCHEDULED_TIP,
        GameFieldName.PREGAME_INTEREST,
        GameFieldName.PREGAME_STANDINGS,
        GameFieldName.PREGAME_AVAILABILITY,
    )},
    GameFieldName.WATCHABILITY_VERDICT: DisclosureLayer.WATCHABILITY,
    GameFieldName.WATCHABILITY_REASON: DisclosureLayer.WHY,
    **{name: DisclosureLayer.FULL for name in (
        GameFieldName.IN_GAME_STATUS,
        GameFieldName.HOME_SCORE,
        GameFieldName.AWAY_SCORE,
        GameFieldName.RESULT,
        GameFieldName.BOX_SCORE,
        GameFieldName.RECAP,
        GameFieldName.HIGHLIGHT_URL,
        GameFieldName.HIGHLIGHT_THUMBNAIL,
        GameFieldName.HIGHLIGHT_RUNTIME_SECONDS,
    )},
}


class MediaSensitivity(str, Enum):
    GENERAL = "general"
    PREGAME = "pregame"
    OUTCOME_DEPENDENT = "outcome_dependent"
    UNKNOWN = "unknown"


class MediaFieldName(str, Enum):
    HEADLINE = "headline"
    EXCERPT = "excerpt"
    THUMBNAIL_URL = "thumbnail_url"
    RUNTIME_SECONDS = "runtime_seconds"


@dataclass(frozen=True, slots=True)
class GameContext:
    game_id: UUID
    time_cursor: datetime
    tip_at: datetime | None
    protection_ends_at: datetime | None = None
    acknowledged: bool = False
    explicit_full_reveal: bool = False


@dataclass(frozen=True, slots=True)
class GameField:
    name: GameFieldName
    value: Scalar
    available_at: datetime | None
    observed_at: datetime | None
    related_game_ids: frozenset[UUID] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class GameProjection:
    game_id: UUID
    disclosure: DisclosureLayer
    fields: dict[str, Scalar]


@dataclass(frozen=True, slots=True)
class MediaField:
    name: MediaFieldName
    value: Scalar
    available_at: datetime | None
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class MediaItem:
    item_id: str
    available_at: datetime | None
    observed_at: datetime | None
    sensitivity: MediaSensitivity
    related_game_ids: frozenset[UUID]
    fields: tuple[MediaField, ...]


@dataclass(frozen=True, slots=True)
class MediaProjection:
    item_id: str
    fields: dict[str, Scalar]


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None or moment.tzinfo is None or moment.utcoffset() is None:
        return None
    return moment.astimezone(timezone.utc)


def _cursor(value: datetime) -> datetime:
    result = _utc(value)
    if result is None:
        raise ValueError("time_cursor must be timezone-aware")
    return result


def _known_by(available_at: datetime | None, observed_at: datetime | None, cursor: datetime) -> bool:
    """Both provenance times must be known and no later than the cursor."""
    available = _utc(available_at)
    observed = _utc(observed_at)
    return available is not None and observed is not None and available <= cursor and observed <= cursor


def _timestamped(available_at: datetime | None, observed_at: datetime | None) -> bool:
    """For an explicit per-game reveal, provenance must exist but may be post-cursor."""
    return _utc(available_at) is not None and _utc(observed_at) is not None


def game_is_unsealed(game: GameContext) -> bool:
    cursor = _cursor(game.time_cursor)
    if game.acknowledged:
        return True
    boundary, tip = _utc(game.protection_ends_at), _utc(game.tip_at)
    # A corrupt/unknown boundary cannot silently unseal a game.
    return boundary is not None and tip is not None and boundary > tip and cursor >= boundary


def _permitted_layer(game: GameContext, requested: DisclosureLayer) -> DisclosureLayer:
    if requested == DisclosureLayer.FULL:
        if game_is_unsealed(game) or game.explicit_full_reveal:
            return DisclosureLayer.FULL
        return DisclosureLayer.PREGAME  # FULL requires an explicit, authorized reveal.
    return requested


def project_game(game: GameContext, requested: DisclosureLayer, fields: tuple[GameField, ...]) -> GameProjection:
    """Project typed field allowlist only; never forward a raw game/model mapping.

    A deliberate 'explicit_full_reveal' permits a single game-specific FULL projection.
    Persisting acknowledgement belongs to #14, not this pure function.
    """
    cursor = _cursor(game.time_cursor)
    if type(requested) is not DisclosureLayer:
        raise ValueError("requested layer must be a DisclosureLayer")
    layer = _permitted_layer(game, requested)
    safe: dict[str, Scalar] = {}
    duplicates: set[str] = set()
    for part in fields:
        if not isinstance(part.name, GameFieldName):
            continue
        minimum = _FIELD_LAYER.get(part.name)
        if minimum is None or minimum > layer or not isinstance(part.value, (str, int, float, bool, type(None))):
            continue
        if part.related_game_ids - {game.game_id}:
            continue  # This field could spoil a different sealed game.
        if minimum == DisclosureLayer.PREGAME:
            tip = _utc(game.tip_at)
            available = _utc(part.available_at)
            if tip is None or available is None or available >= tip:
                continue
            if not _known_by(part.available_at, part.observed_at, cursor):
                continue
        elif not _timestamped(part.available_at, part.observed_at):
            continue
        name = part.name.value
        if name in safe:
            duplicates.add(name)
        else:
            safe[name] = part.value
    for name in duplicates:
        del safe[name]  # Ambiguous competing source values fail closed.
    return GameProjection(game_id=game.game_id, disclosure=layer, fields=safe)


def _media_item_visible(item: MediaItem, cursor: datetime, games: dict[UUID, GameContext]) -> bool:
    if not _known_by(item.available_at, item.observed_at, cursor):
        return False
    if not isinstance(item.sensitivity, MediaSensitivity):
        return False
    if item.sensitivity == MediaSensitivity.GENERAL:
        return not item.related_game_ids
    if not item.related_game_ids:
        return False  # Classification without complete game linkage is not evidence.
    related = [games.get(game_id) for game_id in item.related_game_ids]
    if any(game is None or _cursor(game.time_cursor) != cursor for game in related):
        return False
    if item.sensitivity == MediaSensitivity.PREGAME:
        return all(
            (tip := _utc(game.tip_at)) is not None and _utc(item.available_at) < tip
            for game in related if game is not None
        )
    if item.sensitivity == MediaSensitivity.OUTCOME_DEPENDENT:
        return all(game_is_unsealed(game) for game in related if game is not None)
    return False


def project_general_media(
    items: tuple[MediaItem, ...],
    *,
    time_cursor: datetime,
    games: dict[UUID, GameContext],
) -> tuple[MediaProjection, ...]:
    """Global feed, including after an individual game is acknowledged.

    Omits entire items if unsafe; no spoiler rewriting or placeholder counts.
    Fields (including image, duration) have independent availability checks.
    """
    cursor = _cursor(time_cursor)
    output: list[MediaProjection] = []
    for item in items:
        if not _media_item_visible(item, cursor, games):
            continue
        safe: dict[str, Scalar] = {}
        duplicates: set[str] = set()
        for part in item.fields:
            if not isinstance(part.name, MediaFieldName) or not isinstance(part.value, (str, int, float, bool, type(None))):
                continue
            if not _known_by(part.available_at, part.observed_at, cursor):
                continue
            name = part.name.value
            if name in safe:
                duplicates.add(name)
            else:
                safe[name] = part.value
        for name in duplicates:
            del safe[name]
        if not isinstance(safe.get("headline"), str) or not safe["headline"].strip():
            continue
        output.append(MediaProjection(item_id=item.item_id, fields=safe))
    return tuple(output)


def order_game_cards(cards: tuple[GameProjection, ...]) -> tuple[GameProjection, ...]:
    """Use safe pregame signal, never hidden postgame scores or favorite teams."""
    def key(card: GameProjection) -> tuple[int, float, str]:
        score = card.fields.get(GameFieldName.PREGAME_INTEREST.value)
        if type(score) not in (int, float) or not isfinite(score):
            return (1, 0.0, str(card.game_id))
        return (0, -float(score), str(card.game_id))

    return tuple(sorted(cards, key=key))


def build_safe_ai_context(
    games: tuple[GameProjection, ...],
    media: tuple[MediaProjection, ...],
) -> dict[str, list[dict[str, object]]]:
    """AI callers accept only policy projections, never unrestricted capture objects."""
    if not all(type(game) is GameProjection for game in games):
        raise TypeError("AI game input must be GameProjection")
    if not all(type(item) is MediaProjection for item in media):
        raise TypeError("AI media input must be MediaProjection")
    return {
        "games": [{"game_id": str(game.game_id), "fields": dict(game.fields)} for game in games],
        "media": [{"item_id": item.item_id, "fields": dict(item.fields)} for item in media],
    }
