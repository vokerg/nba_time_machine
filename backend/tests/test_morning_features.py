"""Synthetic trajectory definitions and refusal of incomplete/corrected evidence."""
from datetime import date, datetime, timezone

from morning_fixtures import scoreboard, summary
from nba_time_machine.sports import espn
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.ranking.scoring import PostgameSignal


def evidence():
    data = summary()
    return espn.summary(data, espn.scoreboard(scoreboard(data), date(2026, 10, 13))[0],
                        datetime(2026, 10, 14, 10, tzinfo=timezone.utc))


def test_metrics_and_zero_signals_are_real_evidence():
    result = trajectory_features(evidence())
    assert result.clutch_ms == 300_000
    assert result.lead_changes == result.winner_max_deficit == result.overtime_periods == 0
    assert result.normalized() == {PostgameSignal.CLUTCH: 1,
        PostgameSignal.LEAD_CHANGES: 0, PostgameSignal.COMEBACK: 0, PostgameSignal.OVERTIME: 0}


def test_rechecks_scores_and_clocks_even_if_flags_claim_complete():
    e = evidence()
    bad = e.plays[2].model_copy(update={"home": 10})
    assert trajectory_features(e.model_copy(update={"plays": e.plays[:2] + (bad,) + e.plays[3:]})) is None
    assert trajectory_features(e.model_copy(update={"plays": e.plays[1:]})) is None
    assert trajectory_features(e.model_copy(update={"status": "pending"})) is None


def test_box_failure_does_not_destroy_valid_trajectory():
    e = evidence()
    assert trajectory_features(e.model_copy(update={"players": (), "box_errors": ("missing_box",)})) is not None


def test_ties_and_winner_deficit_and_clutch_intervals():
    # Change the fixture so the eventual home winner trails early, ties, leads.
    e = evidence()
    plays = list(e.plays)
    # First period becomes away 1, then home ties: all period totals unchanged.
    plays[1] = plays[1].model_copy(update={"home": 0, "away": 1})
    plays[2] = plays[2].model_copy(update={"home": 1, "away": 1})
    result = trajectory_features(e.model_copy(update={"plays": tuple(plays)}))
    assert result.winner_max_deficit == result.lead_changes == 1
    # In Q4 the last scoring play is at 11 minutes: cap the interval to last 5.
    assert result.clutch_ms == 300_000
