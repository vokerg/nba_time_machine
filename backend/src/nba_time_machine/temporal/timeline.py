from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID


class TimelineError(RuntimeError):
    """Base class for timeline-domain failures."""


class TimelineNotInitializedError(TimelineError):
    """Raised when a profile has no persisted timeline state."""


class TimelineAlreadyInitializedError(TimelineError):
    """Raised when initialization is attempted more than once."""


class TimelineWouldMoveBackwardError(TimelineError):
    def __init__(self, *, current: datetime, requested: datetime) -> None:
        self.current = current
        self.requested = requested
        super().__init__(
            f"timeline cannot move backward from {current.isoformat()} "
            f"to {requested.isoformat()}"
        )


class TimelineTimestampError(TimelineError):
    """Raised when a cursor or boundary is missing timezone information."""


@dataclass(frozen=True, slots=True)
class TimelineState:
    profile_id: UUID
    time_cursor: datetime
    initialized_at: datetime
    updated_at: datetime

    def has_reached(self, moment: datetime) -> bool:
        """Return whether this timeline has reached a supplied safe-exposure boundary."""

        return self.time_cursor >= normalize_timestamp(moment)


class TimelineRepository(Protocol):
    async def get(self, profile_id: UUID) -> TimelineState | None: ...

    async def initialize(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState | None: ...

    async def advance_if_not_backward(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState | None: ...


class TimelineService:
    def __init__(self, repository: TimelineRepository) -> None:
        self._repository = repository

    async def initialize(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState:
        normalized = normalize_timestamp(time_cursor)
        state = await self._repository.initialize(profile_id, normalized)
        if state is None:
            raise TimelineAlreadyInitializedError(
                f"timeline already initialized for profile {profile_id}"
            )
        return state

    async def resume(self, profile_id: UUID) -> TimelineState:
        state = await self._repository.get(profile_id)
        if state is None:
            raise TimelineNotInitializedError(
                f"timeline is not initialized for profile {profile_id}"
            )
        return state

    async def advance(
        self,
        profile_id: UUID,
        time_cursor: datetime,
    ) -> TimelineState:
        normalized = normalize_timestamp(time_cursor)
        updated = await self._repository.advance_if_not_backward(
            profile_id,
            normalized,
        )
        if updated is not None:
            return updated

        current = await self._repository.get(profile_id)
        if current is None:
            raise TimelineNotInitializedError(
                f"timeline is not initialized for profile {profile_id}"
            )
        raise TimelineWouldMoveBackwardError(
            current=current.time_cursor,
            requested=normalized,
        )

    @staticmethod
    def has_advanced_past_game(
        state: TimelineState,
        *,
        protection_ends_at: datetime,
    ) -> bool:
        """Evaluate a caller-supplied game protection boundary.

        The timeline layer does not infer a game's protection boundary from scores,
        status, or media. The spoiler-policy layer supplies the earliest defensible
        timestamp after which the game no longer needs sealing. Equality counts as
        reached because information at the cursor is part of the reconstructed world.
        """

        return state.has_reached(protection_ends_at)


def normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimelineTimestampError("timeline timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
