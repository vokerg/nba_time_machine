"""Trusted application boundary for per-game layered disclosure.

Only the server-selected game reader supplies fields and provenance; clients
can request a disclosure level but cannot supply GameContext or source data.
An explicit reveal writes one durable acknowledgement, never the global cursor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from nba_time_machine.spoilers.policy import (
    DisclosureLayer,
    GameContext,
    GameField,
    GameProjection,
    MediaItem,
    MediaProjection,
    game_is_unsealed,
    project_game,
    project_general_media,
)
from nba_time_machine.temporal.timeline import TimelineService, TimelineState


class GameNotFoundError(LookupError):
    """Unknown game identity."""


class SealedGameError(PermissionError):
    """A sealed game's full result needs a deliberate reveal command."""


class GameResultNotAvailableError(RuntimeError):
    """Do not pre-acknowledge future games with no trusted final result."""


@dataclass(frozen=True, slots=True)
class TrustedGameSnapshot:
    game_id: UUID
    tip_at: datetime | None
    protection_ends_at: datetime | None
    fields: tuple[GameField, ...]
    full_available: bool = False


@dataclass(frozen=True, slots=True)
class DisclosedGame:
    state: str
    projection: GameProjection


class GameSnapshotRepository(Protocol):
    async def get(self, game_id: UUID, *, time_cursor: datetime) -> TrustedGameSnapshot | None: ...


class GameAcknowledgementRepository(Protocol):
    async def is_acknowledged(self, profile_id: UUID, game_id: UUID) -> bool: ...
    async def acknowledge(self, profile_id: UUID, game_id: UUID) -> None: ...


class GameDisclosureService:
    def __init__(
        self,
        timeline: TimelineService,
        games: GameSnapshotRepository,
        acknowledgements: GameAcknowledgementRepository,
    ) -> None:
        self._timeline = timeline
        self._games = games
        self._acknowledgements = acknowledgements

    async def _context(
        self, profile_id: UUID, game_id: UUID, timeline: TimelineState,
    ) -> tuple[GameContext, TrustedGameSnapshot]:
        snapshot = await self._games.get(game_id, time_cursor=timeline.time_cursor)
        if snapshot is None:
            raise GameNotFoundError(f"game {game_id} not found")
        if type(snapshot) is not TrustedGameSnapshot or snapshot.game_id != game_id:
            raise TypeError("trusted game reader returned an invalid snapshot")
        acknowledged = await self._acknowledgements.is_acknowledged(profile_id, game_id)
        return (
            GameContext(
                game_id=game_id,
                time_cursor=timeline.time_cursor,
                tip_at=snapshot.tip_at,
                protection_ends_at=snapshot.protection_ends_at,
                acknowledged=acknowledged,
            ),
            snapshot,
        )

    async def disclose(
        self, profile_id: UUID, game_id: UUID, layer: DisclosureLayer,
    ) -> DisclosedGame:
        if type(layer) is not DisclosureLayer:
            raise ValueError("invalid disclosure layer")
        timeline = await self._timeline.resume(profile_id)
        context, snapshot = await self._context(profile_id, game_id, timeline)
        unsealed = game_is_unsealed(context)
        if layer is DisclosureLayer.FULL and not unsealed:
            raise SealedGameError("full result requires an explicit reveal")
        projection = project_game(context, layer, snapshot.fields)
        return DisclosedGame(
            state="acknowledged" if unsealed else "sealed",
            projection=projection,
        )

    async def reveal_full(self, profile_id: UUID, game_id: UUID) -> DisclosedGame:
        timeline = await self._timeline.resume(profile_id)
        context, snapshot = await self._context(profile_id, game_id, timeline)
        if not game_is_unsealed(context):
            if not snapshot.full_available:
                raise GameResultNotAvailableError(
                    "trusted final result is not available for this game"
                )
            await self._acknowledgements.acknowledge(profile_id, game_id)
            context = replace(context, acknowledged=True, explicit_full_reveal=True)
        # Games unsealed by timeline advancement do not get fake watched/reveal rows.
        return DisclosedGame(
            state="acknowledged",
            projection=project_game(context, DisclosureLayer.FULL, snapshot.fields),
        )

    async def general_media(
        self, profile_id: UUID, items: tuple[MediaItem, ...],
    ) -> tuple[MediaProjection, ...]:
        """Global feed still uses the cursor, even after a per-game reveal."""
        if any(type(item) is not MediaItem for item in items):
            raise TypeError("general media requires trusted typed MediaItem records")
        timeline = await self._timeline.resume(profile_id)
        ids = {game_id for item in items for game_id in item.related_game_ids}
        games: dict[UUID, GameContext] = {}
        for game_id in ids:
            try:
                context, _ = await self._context(profile_id, game_id, timeline)
            except GameNotFoundError:
                continue  # The policy fails closed on incomplete game linkage.
            games[game_id] = context
        return project_general_media(
            items, time_cursor=timeline.time_cursor, games=games,
        )
