"""Synthetic trajectory definitions and refusal of incomplete/corrected evidence."""
from datetime import date, datetime, timezone

from morning_fixtures import scoreboard, summary
from nba_time_machine.sports import espn
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.ranking.scoring import PostgameSignal
from nba_time_machine.sports.morning_models import Play


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


def test_overtime_is_measured_and_its_clutch_time_is_counted():
    e = evidence()
    plays = [p for p in e.plays if not p.game_end]
    end = plays.pop()  # Fourth-period end; insert a tying free throw before it.
    plays.append(Play(external_id="tie", index=100, period=4, remaining_ms=60_000,
        home=4, away=4, kind="ft", scoring=True, points=1))
    plays.append(end.model_copy(update={"away": 4}))
    plays.extend([
        Play(external_id="ot-start", index=101, period=5, remaining_ms=300_000,
             home=4, away=4, kind="start"),
        Play(external_id="ot-point", index=102, period=5, remaining_ms=200_000,
             home=5, away=4, kind="ft", scoring=True, points=1),
        Play(external_id="ot-end", index=103, period=5, remaining_ms=0,
             home=5, away=4, kind="end", period_end=True, game_end=True),
    ])
    result = trajectory_features(e.model_copy(update={
        "plays": tuple(plays),
        "home": e.home.model_copy(update={"periods": (1, 1, 1, 1, 1), "score": 5}),
        "away": e.away.model_copy(update={"periods": (1, 1, 1, 1, 0), "score": 4}),
    }))
    assert result.overtime_periods == 1 and result.clutch_ms == 600_000
    assert result.normalized()[PostgameSignal.OVERTIME] == 1 / 3
