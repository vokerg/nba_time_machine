"""Entirely generated fixtures: NOT real NBA schema or evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from nba_time_machine.research.trajectory import Action, Trace, validate_trace

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def synthetic_trace(periods=4):
    actions = []
    home = away = 0
    for period in range(1, periods + 1):
        duration = 720_000 if period <= 4 else 300_000
        for kind, clock in (("start", duration), ("play", 60_000), ("end", 0)):
            if kind == "play":
                away += 2
            if kind == "end":
                home = away + (1 if period == periods else 0)
            number = len(actions)
            actions.append(Action(event_id=str(number), order=number, period=period,
                                  remaining_ms=clock, home=home, away=away, kind=kind))
    return Trace(provider="synthetic", provider_game_id="fixture", home_team_id="h",
                 away_team_id="a", observed_at=NOW, final_state=True,
                 declared_periods=periods, actions=tuple(actions))


def validate(trace):
    return validate_trace(trace, reference_totals=(trace.actions[-1].home, trace.actions[-1].away))


def replace_action(trace, index, **changes):
    actions = list(trace.actions)
    actions[index] = Action.model_validate({**actions[index].model_dump(), **changes})
    return Trace.model_validate({**trace.model_dump(), "actions": tuple(actions)})


@pytest.mark.parametrize("periods", [4, 5, 6])
def test_complete_synthetic_trace_with_comeback_and_overtime(periods):
    result = validate(synthetic_trace(periods))
    assert result.structurally_complete
    assert result.overtime_periods == periods - 4
    assert result.winner_max_deficit == 2
    assert result.lead_changes == 1
    assert result.trusted_final_at is None
    assert not result.canonical_identity_verified
    assert not result.independently_verified_complete


@pytest.mark.parametrize("index,changes,error", [
    (2, {"kind": "play"}, "missing_or_invalid_boundary"),
    (1, {"remaining_ms": 720_000, "order": 0}, "unordered_actions"),
    (2, {"remaining_ms": 70_000}, "clock_reversed"),
    (4, {"home": 0, "away": 0}, "score_regressed"),
    (3, {"home": 1}, "score_changed_between_periods"),
    (1, {"revision_at": NOW + timedelta(seconds=1)}, "future_revision"),
])
def test_partial_or_contradictory_trace_emits_no_metrics(index, changes, error):
    result = validate(replace_action(synthetic_trace(), index, **changes))
    assert error in result.errors
    assert not result.structurally_complete
    assert result.lead_changes is None
    assert result.winner_max_deficit is None
    assert result.overtime_periods is None


def test_missing_period_and_missing_reference_fail_closed():
    trace = synthetic_trace()
    trace = trace.model_copy(update={"actions": tuple(a for a in trace.actions if a.period != 2)})
    assert "missing_or_extra_period" in validate(trace).errors
    assert not validate_trace(synthetic_trace(), reference_totals=None).structurally_complete
    assert not validate_trace(synthetic_trace(), reference_totals=(0, 0)).structurally_complete


def test_nonfinal_tied_final_and_unearned_overtime():
    trace = synthetic_trace()
    assert "not_final" in validate(trace.model_copy(update={"final_state": False})).errors
    assert "tied_final" in validate(replace_action(trace, -1, home=8, away=8)).errors
    trace = synthetic_trace(5)
    assert "overtime_without_tied_boundary" in validate(replace_action(trace, 11, home=9)).errors


def test_exact_repeat_collapses_but_conflict_needs_revision_proof():
    trace = synthetic_trace()
    duplicate = trace.actions[1]
    assert validate(trace.model_copy(update={"actions": trace.actions + (duplicate,)})).revisions_collapsed == 1
    conflict = duplicate.model_copy(update={"home": 1})
    result = validate(trace.model_copy(update={"actions": trace.actions + (conflict,)}))
    assert "ambiguous_revision" in result.errors


def test_explicit_correction_uses_latest_version_without_double_counting():
    trace = synthetic_trace()
    actions = list(trace.actions)
    correct = actions[1].model_copy(update={"revision_at": NOW})
    actions[1] = correct.model_copy(update={"home": 1, "revision_at": NOW - timedelta(seconds=1)})
    result = validate_trace(trace.model_copy(update={"actions": tuple(actions) + (correct,)}),
                            reference_totals=(9, 8))
    assert result.structurally_complete
    assert result.revisions_collapsed == 1
    assert result.winner_max_deficit == 2


@pytest.mark.parametrize("changes", [{"observed_at": datetime(2026, 1, 1)},
                                      {"home_team_id": "a"}, {"provider_game_id": ""}])
def test_typed_identity_and_timezone_contract(changes):
    with pytest.raises(ValidationError):
        Trace.model_validate({**synthetic_trace().model_dump(), **changes})


@pytest.mark.parametrize("changes", [{"home": True}, {"home": "2"},
                                      {"remaining_ms": -1}, {"period": 0},
                                      {"period": 5, "remaining_ms": 720_000}])
def test_no_numeric_coercion_or_invalid_clock(changes):
    with pytest.raises(ValidationError):
        Action.model_validate({**synthetic_trace().actions[0].model_dump(), **changes})
