"""Completed-season source validation and early-season prior behavior."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from nba_time_machine.ranking.pregame import RecordSettings, record_preview, expectation, PregameExpectation
from nba_time_machine.ranking.season_strength import prior_rate
from nba_time_machine.sports.morning_models import TEAM_NAMES
from nba_time_machine.sports.season_foundation import PriorTeam, parse_foundation

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def payloads():
    entries = []
    for index, (abbr, name) in enumerate(sorted(TEAM_NAMES.items()), 101):
        entries.append({'team': {'id': str(index), 'abbreviation': abbr, 'displayName': name},
                        'stats': [{'name': 'wins', 'value': 41.0}, {'name': 'losses', 'value': 41.0}]})
    standings = {'abbreviation': 'NBA', 'season': {'year': 2026, 'endDate': '2026-06-27T06:59Z'},
                 'children': [{'standings': {'entries': entries[:15]}}, {'standings': {'entries': entries[15:]}}]}
    ids = {e['team']['abbreviation']: e['team']['id'] for e in entries}
    finalists = [ids['NYK'], ids['SAS']]
    finals = {'leagues': [{'abbreviation': 'NBA'}], 'events': [{'id': '12345', 'date': '2026-06-14T00:30Z',
        'season': {'year': 2026, 'type': 3}, 'status': {'type': {'completed': True}},
        'competitions': [{'notes': [{'headline': 'NBA Finals - Game 5'}],
            'series': {'completed': True, 'type': 'playoff', 'totalCompetitions': 7,
                       'competitors': [{'id': finalists[0], 'wins': 4}, {'id': finalists[1], 'wins': 1}]},
            'competitors': [{'id': tid, 'winner': i == 0, 'score': str(100-i*10)} for i, tid in enumerate(finalists)]}]}]}
    return standings, finals


def test_normalized_foundation_requires_complete_regular_season_and_explicit_title():
    standings, finals = payloads()
    result = parse_foundation(standings, finals, '2025-2026', NOW)
    assert len(result.teams) == 30
    assert next(t for t in result.teams if t.team == 'NYK').achievement == 'champion'
    assert next(t for t in result.teams if t.team == 'SAS').achievement == 'finalist'
    assert all(t.wins + t.losses == 82 for t in result.teams)


@pytest.mark.parametrize('fault', ['partial_records', 'wrong_year', 'duplicate_team', 'no_title', 'false_title',
                                  'unfinished', 'wrong_round', 'future', 'ambiguous', 'fraction', 'boolean'])
def test_untrusted_or_incomplete_prior_is_not_used(fault):
    standings, finals = deepcopy(payloads())
    event = finals['events'][0]
    comp = event['competitions'][0]
    if fault == 'partial_records': standings['children'][0]['standings']['entries'][0]['stats'][0]['value'] = 40
    if fault == 'wrong_year': standings['season']['year'] = 2027
    if fault == 'duplicate_team': standings['children'][0]['standings']['entries'][1] = standings['children'][0]['standings']['entries'][0]
    if fault == 'no_title': finals['events'] = []
    if fault == 'false_title': comp['series']['competitors'][0]['wins'] = 3
    if fault == 'unfinished': event['status']['type']['completed'] = False
    if fault == 'wrong_round': comp['notes'][0]['headline'] = 'East Finals - Game 5'
    if fault == 'future': standings['season']['endDate'] = '2027-06-27T06:59Z'
    if fault == 'ambiguous': finals['events'] *= 2
    if fault == 'fraction': standings['children'][0]['standings']['entries'][0]['stats'][0]['value'] = 40.5
    if fault == 'boolean': standings['children'][0]['standings']['entries'][0]['stats'][0]['value'] = True
    with pytest.raises(ValueError): parse_foundation(standings, finals, '2025-2026', NOW)


def context(games=3, champion=True):
    teams = [PriorTeam(team='NYK', external_id='18', wins=53, losses=29,
                       achievement='champion' if champion else 'none'),
             PriorTeam(team='OKC', external_id='25', wins=64, losses=18, achievement='none')]
    return {'status': 'available', 'basis': 'known-pre-tip',
            'home': {'team': 'NYK', 'wins': 0, 'losses': games, 'games_played': games,
                     'prior': {**teams[0].model_dump(), 'win_rate': prior_rate(teams[0])}},
            'away': {'team': 'OKC', 'wins': games, 'losses': 0, 'games_played': games,
                     'prior': {**teams[1].model_dump(), 'win_rate': prior_rate(teams[1])}},
            'prior_provenance': {'source_ref': 'season-strength-v1:prior', 'season': '2025-2026',
                'observed_at': NOW, 'available_at': NOW, 'known_pre_tip': True}}


def test_champion_at_zero_and_three_remains_a_contender_and_title_adds_credit():
    result = record_preview(context(), RecordSettings())
    assert result['calculation']['home_smoothed_win_pct'] > .64
    assert result['calculation']['home_strength_magnitude'] > .55
    assert result['bonus'] > record_preview(context(champion=False), RecordSettings())['bonus']
    assert record_preview(context(0), RecordSettings())['bonus'] > 0
    assert record_preview(context(1), RecordSettings())['bonus'] > 0
    value = expectation(context(), source_ref='pregame-records:current', observed_at=NOW, available_at=NOW)
    assert PregameExpectation.model_validate(value).model == 'pregame-records-v2'
    assert value['teams'][0]['wins'] == 0 and value['teams'][0]['losses'] == 3
    assert value['overall_points'] == result['bonus']


def test_current_season_takes_over_and_prior_cannot_rescue_a_poor_full_season():
    weights = [record_preview(context(games), RecordSettings())['calculation']['home_prior_weight'] for games in (0, 3, 10, 20, 40, 82)]
    assert weights[0] == 1 and weights[-2:] == [0, 0]
    assert all(a > b for a, b in zip(weights[:4], weights[1:5]))
    late = record_preview(context(40), RecordSettings())
    assert late['calculation']['home_strength_magnitude'] == 0
    assert late['calculation']['away_strength_magnitude'] == 1
    assert late['bonus'] == .8  # the other contender still supplies its own importance


def test_missing_prior_keeps_legacy_behavior_and_late_observation_is_reconstructed():
    original = context(1)
    for side in ('home', 'away'): original[side].pop('prior')
    original.pop('prior_provenance')
    assert record_preview(original, RecordSettings())['bonus'] is None
    c = context()
    c['prior_provenance']['known_pre_tip'] = False
    value = expectation(c, source_ref='pregame-records:current', observed_at=NOW, available_at=NOW)
    assert value['basis'] == 'reconstructed'
    assert not any('score' in t or 'achievement' in t for t in value['teams'])
