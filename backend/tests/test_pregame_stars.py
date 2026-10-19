"""Shared reputation arithmetic with explicitly different participation inputs."""
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from test_star_power import evidence, snapshot, NOW
from nba_time_machine.ranking.star_power import StarSettings, team_star_power, matchup_star_power, star_preview
from nba_time_machine.ranking.pregame import combine_expectation, PregameExpectation
from nba_time_machine.ranking.scoring import (FeatureObservation, PostgameSignal, score_postgame,
    add_star_power, add_matchup_expectation, score_evidence_is_consistent, component_points, STAR_OVERALL_VERSION)


def potential():
    settings = StarSettings()
    teams = []
    for team, rank in [('BOS', 1), ('NYK', 2)]:
        players, _, normalized = team_star_power([{'name':f'Fixture {rank}', 'rank':rank, 'factor':1.}], settings)
        teams.append({'team':team,'normalized':normalized,'players':players})
    metric = matchup_star_power(teams[0]['normalized'], teams[1]['normalized'], settings)
    return {'rating':round(metric*10,4),'overall_points':round(metric*1.5,4), 'explanation':'Roster potential; availability unconfirmed.',
        'teams':teams,'evidence':[{'source_ref':f'fixture:{i}','observed_at':NOW-timedelta(days=1),
        'available_at':NOW-timedelta(days=1)} for i in range(3)]}


def test_star_potential_survives_missing_records_and_uses_shared_formula():
    stars = potential()
    # Public rows discard the internal factor, which is an assumption, not minutes.
    for team in stars['teams']:
        for player in team['players']:
            player.pop('factor')
    value = combine_expectation(None, stars)
    assert value['coverage']=='stars-only' and value['basis']=='known-pre-tip'
    assert value['rating']==stars['rating'] and value['sample_confidence'] is None
    assert all('wins' not in t for t in value['teams'])
    assert PregameExpectation.model_validate(value).star_power is not None
    assert combine_expectation(None, None) is None
    actual = star_preview(evidence(), snapshot(), StarSettings())
    assert actual['bonus']==stars['overall_points']
    absent = evidence().model_copy(update={'players':tuple(p.model_copy(update={
        'did_not_play':True, 'minutes':0., 'statistics':{}}) if p.external_id=='1' else
        p.model_copy(update={'minutes':60.}) if p.team_id=='1' else p for p in evidence().players)})
    # Incomplete minutes do not become assumed participation.
    assert star_preview(absent,snapshot(),StarSettings())['bonus'] is None


def test_realized_star_version_arithmetic_cap_and_corruption():
    for drama in (0., .5, 1.):
        base = score_postgame(uuid4(), {PostgameSignal.CLUTCH:FeatureObservation(
            drama,'fixture:drama',NOW,NOW)},final_at=NOW,as_of=NOW)
        overall = add_star_power(base,.8,source_ref='fixture:stars',observed_at=NOW,available_at=NOW)
        assert overall.model_version==STAR_OVERALL_VERSION and overall.value==min(10,base.value+1.2)
        assert score_evidence_is_consistent(overall)
        assert abs(sum(component_points(overall))-overall.value)<.001
        assert not score_evidence_is_consistent(replace(overall,value=overall.value-.1))
        assert not score_evidence_is_consistent(replace(overall,components=overall.components+overall.components[-1:]))


def test_records_and_realized_stars_are_each_added_once_before_cap():
    base = score_postgame(uuid4(), {PostgameSignal.CLUTCH:FeatureObservation(
        .8,'fixture:drama',NOW,NOW)},final_at=NOW,as_of=NOW)
    records=add_matchup_expectation(base,.8,source_ref='fixture:records',observed_at=NOW,available_at=NOW)
    result=add_star_power(records,.8,source_ref='fixture:stars',observed_at=NOW,available_at=NOW)
    assert result.value==10 and score_evidence_is_consistent(result)
    assert [p.signal for p in result.components]==['clutch','matchup_expectation','star_power']
    assert abs(sum(component_points(result))-10)<.001
