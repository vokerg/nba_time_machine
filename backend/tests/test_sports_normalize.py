from datetime import timezone

import pytest

from nba_time_machine.sports.errors import SportsProviderResponseError
from nba_time_machine.sports.normalize import normalize_thesportsdb_event


def _event(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "idEvent": "2601626",
        "idLeague": "4387",
        "strSeason": "2026-2027",
        "idHomeTeam": "134873",
        "strHomeTeam": "Indiana Pacers",
        "idAwayTeam": "134886",
        "strAwayTeam": "Minnesota Timberwolves",
        "strEvent": "Indiana Pacers vs Minnesota Timberwolves",
        "strStatus": "NS",
        "strPostponed": "no",
        "strTimestamp": "2026-10-07T23:00:00",
        "dateEvent": "2026-10-07",
        "dateEventLocal": "2026-10-07",
        "strTime": "23:00:00",
        "strTimeLocal": "19:00:00",
        "intRound": "1",
        "intHomeScore": None,
        "intAwayScore": None,
    }
    payload.update(overrides)
    return payload


def test_normalizes_verified_scheduled_nba_event() -> None:
    normalized = normalize_thesportsdb_event(_event())

    assert normalized.external_event_id == "2601626"
    assert normalized.season_label == "2026-2027"
    assert normalized.home_team.external_id == "134873"
    assert normalized.away_team.external_id == "134886"
    assert normalized.status == "scheduled"
    assert normalized.home_score is None
    assert normalized.away_score is None
    assert normalized.scheduled_tip_at is not None
    assert normalized.scheduled_tip_at.tzinfo == timezone.utc
    assert normalized.scheduled_tip_at.isoformat() == "2026-10-07T23:00:00+00:00"
    assert (
        normalized.metadata["provider_time_assumption"]
        == "naive_iso_assumed_utc"
    )


def test_normalizes_verified_finished_nba_event() -> None:
    normalized = normalize_thesportsdb_event(
        _event(
            idEvent="2548850",
            strStatus="FT",
            strTimestamp="2026-10-07T02:00:00",
            intHomeScore="124",
            intAwayScore="98",
        )
    )

    assert normalized.status == "final"
    assert normalized.home_score == 124
    assert normalized.away_score == 98


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [
        ("Q1", "in_progress"),
        ("Q4", "in_progress"),
        ("OT", "in_progress"),
        ("POST", "postponed"),
        ("CANC", "canceled"),
        ("SUSP", "suspended"),
    ],
)
def test_maps_documented_basketball_statuses(
    provider_status: str,
    expected: str,
) -> None:
    normalized = normalize_thesportsdb_event(
        _event(strStatus=provider_status)
    )
    assert normalized.status == expected


def test_rejects_provider_status_without_explicit_semantics() -> None:
    with pytest.raises(SportsProviderResponseError, match="Unsupported"):
        normalize_thesportsdb_event(_event(strStatus="AWD"))


def test_rejects_score_on_scheduled_event() -> None:
    with pytest.raises(SportsProviderResponseError, match="Scheduled"):
        normalize_thesportsdb_event(_event(intHomeScore="1"))
