"""Offline NBA feature derivation; never a ranking materialization test."""
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from nba_time_machine.ranking.feature_candidates import (
    OvertimeCandidate,
    thesportsdb_overtime_candidate,
)
from nba_time_machine.ranking.scoring import PostgameSignal
from nba_time_machine.sports.normalize import normalize_thesportsdb_event


def _nba_event(**overrides: object) -> dict[str, object]:
    # Valid TheSportsDB NBA event structure; ID is a public historical AOT event.
    event: dict[str, object] = {
        "idEvent": "2358414",
        "idLeague": "4387",
        "strSeason": "2025-2026",
        "idHomeTeam": "1",
        "strHomeTeam": "Detroit Pistons",
        "idAwayTeam": "2",
        "strAwayTeam": "Atlanta Hawks",
        "strStatus": "AOT",
        "strPostponed": "no",
        "strTimestamp": "2026-03-25T23:00:00+00:00",
        "intHomeScore": "129",
        "intAwayScore": "130",
    }
    event.update(overrides)
    return event


def test_aot_yields_only_a_positive_non_persistent_candidate() -> None:
    normalized = normalize_thesportsdb_event(_nba_event())
    candidate = thesportsdb_overtime_candidate(normalized)

    assert candidate == OvertimeCandidate(
        provider="thesportsdb",
        external_event_id="2358414",
        signal=PostgameSignal.OVERTIME,
        overtime_occurred=True,
        provider_status="AOT",
    )
    # No score, game UUID, as-of time, or unreviewed claim of source trust.
    assert set(asdict(candidate)) == {
        "provider", "external_event_id", "signal",
        "overtime_occurred", "provider_status",
    }
    with pytest.raises(FrozenInstanceError):
        candidate.overtime_occurred = False


@pytest.mark.parametrize("status", ["FT", "FINAL", "FINISHED", "OT", "Q4"])
def test_other_provider_statuses_do_not_infer_overtime_or_its_absence(
    status: str,
) -> None:
    normalized = normalize_thesportsdb_event(_nba_event(strStatus=status))
    assert thesportsdb_overtime_candidate(normalized) is None


def test_postponed_overrides_apparent_aot() -> None:
    normalized = normalize_thesportsdb_event(
        _nba_event(strPostponed="yes")
    )
    assert normalized.status == "postponed"
    assert thesportsdb_overtime_candidate(normalized) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"intHomeScore": None},
        {"intAwayScore": None},
    ],
)
def test_incomplete_final_result_is_not_evidence(changes: dict) -> None:
    normalized = normalize_thesportsdb_event(_nba_event(**changes))
    assert thesportsdb_overtime_candidate(normalized) is None


def test_only_explicit_provider_status_is_accepted() -> None:
    normalized = normalize_thesportsdb_event(_nba_event())
    assert thesportsdb_overtime_candidate(
        replace(normalized, metadata={"provider_status": "FINAL"})
    ) is None
    assert thesportsdb_overtime_candidate(
        replace(normalized, metadata={"provider_status": ["AOT"]})
    ) is None
    assert thesportsdb_overtime_candidate(
        replace(normalized, metadata={})
    ) is None
    assert thesportsdb_overtime_candidate(
        replace(normalized, metadata=None)
    ) is None


def test_non_nba_provider_event_is_rejected_by_normalization() -> None:
    from nba_time_machine.sports.errors import SportsProviderResponseError

    with pytest.raises(SportsProviderResponseError, match="Expected TheSportsDB NBA"):
        normalize_thesportsdb_event(_nba_event(idLeague="4328"))


def test_normalized_inconsistent_or_forged_status_is_not_enough() -> None:
    normalized = normalize_thesportsdb_event(_nba_event())
    assert thesportsdb_overtime_candidate(
        replace(normalized, status="in_progress")
    ) is None
    assert thesportsdb_overtime_candidate(None) is None
    assert thesportsdb_overtime_candidate(
        replace(normalized, home_score=True)
    ) is None
