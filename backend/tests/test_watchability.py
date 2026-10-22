"""Production exceptional thresholds, bounded addition and archive integrity."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from nba_time_machine.ranking.entertainment import PlayerSettings, player_assessment
from nba_time_machine.ranking.scoring import (
    FeatureObservation, PostgameSignal, score_postgame, add_entertainment,
    add_matchup_expectation, add_star_power, component_points, score_evidence_is_consistent,
    WATCHABILITY_VERSION,
)


def player(**stats):
    s = dict(PTS=0, AST=0, REB=0, STL=0, BLK=0, TO=0) | stats
    return {'statistics': s, 'true_shooting': .75,
            'double_digit_categories': sum(s[k] >= 10 for k in ('PTS','AST','REB','STL','BLK'))}


@pytest.mark.parametrize('stats', [dict(PTS=25), dict(PTS=40), dict(AST=15), dict(REB=20),
    dict(STL=4, BLK=4), dict(PTS=25, AST=10, REB=10)])
def test_ordinary_production_gets_no_exceptional_credit(stats):
    assert player_assessment(player(**stats), PlayerSettings())['severity'] == 0


@pytest.mark.parametrize('stat,floor,peak', [('PTS',40,60), ('AST',15,25), ('REB',20,30), ('STL',8,12)])
def test_exceptional_axes_ramp_and_cap(stat, floor, peak):
    config = PlayerSettings()
    assert player_assessment(player(**{stat:floor}), config)['severity'] == 0
    assert 0 < player_assessment(player(**{stat:floor+1}), config)['severity'] < 1
    assert player_assessment(player(**{stat:peak}), config)['severity'] == 1


def base(value=.2):
    now = datetime.now(timezone.utc)
    return score_postgame(uuid4(), {signal: FeatureObservation(value,'fixture',now,now)
        for signal in (PostgameSignal.CLUTCH, PostgameSignal.LEAD_CHANGES, PostgameSignal.COMEBACK, PostgameSignal.OVERTIME)},
        final_at=now, as_of=now)


def enrich(score, player=1., patterns=0.):
    return add_entertainment(score, player=player, patterns=patterns, source_ref='box-fixture',
        observed_at=score.as_of, available_at=score.as_of)


def test_role_player_can_lift_low_drama_game_and_components_reconcile():
    # No ranking or player-name input exists in the production calculation.
    score = enrich(base())
    assert score.model_version == WATCHABILITY_VERSION and score.value == 6
    assert score_evidence_is_consistent(score)
    assert sum(component_points(score)) == pytest.approx(score.value, abs=.001)
    assert enrich(base(), player=None).value == 2
    assert not any(p.signal=='individual_performance' for p in enrich(base(), player=None).components)


def test_all_families_stack_then_cap_and_legacy_is_immutable():
    old = base(.7)
    with_records = add_matchup_expectation(old, .5, source_ref='record', observed_at=old.as_of, available_at=old.as_of)
    with_stars = add_star_power(with_records, .5, source_ref='stars', observed_at=old.as_of, available_at=old.as_of)
    score = enrich(with_stars, patterns=1.)
    assert old.value == 7 and score.value == 10
    assert score_evidence_is_consistent(score)
    assert sum(component_points(score)) == pytest.approx(10, abs=.001)
    for bad in [replace(score, value=9.9), replace(score, components=score.components+score.components[-1:]),
                replace(score, components=score.components[:-1]+(replace(score.components[-1], weight=4),))]:
        assert not score_evidence_is_consistent(bad)


def test_future_or_invalid_performance_cannot_be_archived():
    score = base()
    with pytest.raises(ValueError):
        add_entertainment(score, player=1., patterns=0., source_ref='future',
            observed_at=score.as_of+timedelta(seconds=1), available_at=score.as_of)
    for value in (True, -1., 1.1, float('nan')):
        with pytest.raises(ValueError): enrich(score, player=value)
