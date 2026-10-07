from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nba_time_machine.sports.contracts import (
    NormalizedGameObservation,
    NormalizedProviderTeam,
)
from nba_time_machine.sports.errors import SportsProviderResponseError

_SCHEDULED_STATUSES = {
    "NS",
    "NOT STARTED",
    "SCHEDULED",
    "TBD",
    "TIME TO BE DEFINED",
}
_IN_PROGRESS_STATUSES = {"Q1", "Q2", "Q3", "Q4", "OT", "BT", "HT", "LIVE"}
_FINAL_STATUSES = {"FT", "AOT", "FINAL", "FINISHED", "GAME FINISHED"}
_POSTPONED_STATUSES = {"POST", "PST", "POSTPONED", "GAME POSTPONED"}
_CANCELED_STATUSES = {"CANC", "CANCELLED", "CANCELED", "GAME CANCELLED"}
_SUSPENDED_STATUSES = {"SUSP", "SUSPENDED", "GAME SUSPENDED"}


def normalize_thesportsdb_event(
    event: dict[str, Any],
) -> NormalizedGameObservation:
    """Normalize only TheSportsDB fields verified for the NBA event feed."""

    external_event_id = _required_text(event, "idEvent")
    league_id = _required_text(event, "idLeague")
    if league_id != "4387":
        raise SportsProviderResponseError(
            f"Expected TheSportsDB NBA league 4387, got {league_id}"
        )

    season_label = _required_text(event, "strSeason")
    home_team = NormalizedProviderTeam(
        external_id=_required_text(event, "idHomeTeam"),
        name=_required_text(event, "strHomeTeam"),
    )
    away_team = NormalizedProviderTeam(
        external_id=_required_text(event, "idAwayTeam"),
        name=_required_text(event, "strAwayTeam"),
    )

    status = _normalize_status(
        event.get("strStatus"),
        postponed=event.get("strPostponed"),
    )
    home_score = _optional_int(event.get("intHomeScore"), "intHomeScore")
    away_score = _optional_int(event.get("intAwayScore"), "intAwayScore")
    scheduled_tip_at, time_assumption = _parse_provider_timestamp(
        event.get("strTimestamp")
    )

    if status == "scheduled" and (
        home_score is not None or away_score is not None
    ):
        raise SportsProviderResponseError(
            "Scheduled TheSportsDB event unexpectedly contained a score"
        )

    return NormalizedGameObservation(
        external_event_id=external_event_id,
        season_label=season_label,
        home_team=home_team,
        away_team=away_team,
        status=status,
        scheduled_tip_at=scheduled_tip_at,
        home_score=home_score,
        away_score=away_score,
        metadata={
            "provider_event_name": event.get("strEvent"),
            "provider_status": event.get("strStatus"),
            "provider_postponed": event.get("strPostponed"),
            "provider_timestamp": event.get("strTimestamp"),
            "provider_date": event.get("dateEvent"),
            "provider_date_local": event.get("dateEventLocal"),
            "provider_time": event.get("strTime"),
            "provider_time_local": event.get("strTimeLocal"),
            "provider_round": event.get("intRound"),
            "provider_time_assumption": time_assumption,
        },
    )


def _normalize_status(value: object, *, postponed: object) -> str:
    postponed_text = _optional_text(postponed)
    if postponed_text and postponed_text.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }:
        return "postponed"

    status = _optional_text(value)
    if status is None:
        raise SportsProviderResponseError(
            "TheSportsDB NBA event is missing strStatus"
        )

    normalized = " ".join(status.strip().upper().split())
    if normalized in _SCHEDULED_STATUSES:
        return "scheduled"
    if normalized in _IN_PROGRESS_STATUSES:
        return "in_progress"
    if normalized in _FINAL_STATUSES:
        return "final"
    if normalized in _POSTPONED_STATUSES:
        return "postponed"
    if normalized in _CANCELED_STATUSES:
        return "canceled"
    if normalized in _SUSPENDED_STATUSES:
        return "suspended"

    # AWD/ABD and any new provider code require an explicit product decision.
    raise SportsProviderResponseError(
        f"Unsupported TheSportsDB NBA event status: {status!r}"
    )


def _parse_provider_timestamp(value: object) -> tuple[datetime | None, str | None]:
    raw = _optional_text(value)
    if raw is None:
        return None, None

    text = raw.strip()
    if not text:
        return None, None

    if text.isdigit():
        return (
            datetime.fromtimestamp(int(text), tz=timezone.utc),
            "unix_timestamp_utc",
        )

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SportsProviderResponseError(
            f"Unsupported TheSportsDB strTimestamp format: {text!r}"
        ) from exc

    if parsed.tzinfo is None:
        # The NBA feed observed on 2026-10-07 used naive ISO timestamps whose
        # values aligned with UTC tip times. Preserve the raw value in metadata
        # and make the assumption explicit rather than silently localizing it.
        return parsed.replace(tzinfo=timezone.utc), "naive_iso_assumed_utc"

    return parsed.astimezone(timezone.utc), "offset_aware_normalized_utc"


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = _optional_text(payload.get(field))
    if value is None or not value.strip():
        raise SportsProviderResponseError(
            f"TheSportsDB NBA event is missing {field}"
        )
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    raise SportsProviderResponseError(
        f"Expected text-compatible provider value, got {type(value).__name__}"
    )


def _optional_int(value: object, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SportsProviderResponseError(
            f"TheSportsDB {field} must be an integer or null"
        )
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise SportsProviderResponseError(
            f"TheSportsDB {field} must be an integer or null"
        ) from exc
    if parsed < 0:
        raise SportsProviderResponseError(
            f"TheSportsDB {field} must be non-negative"
        )
    return parsed
