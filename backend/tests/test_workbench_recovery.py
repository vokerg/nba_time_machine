"""Synthetic surplus-free-throw recovery; no real publisher payloads."""
from datetime import datetime, timezone

import pytest

from morning_fixtures import scoreboard, summary
from nba_time_machine.sports import espn
from nba_time_machine.sports.morning_models import assess
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.workbench.recovery import recover_free_throw


def evidence_pair():
    payload = summary()
    for row in payload['plays']:
        if row['scoringPlay']:
            home = row['homeScore'] > (payload['plays'][payload['plays'].index(row)-1]['homeScore'])
            row['team'] = {'id': '13' if home else '9'}
            row['participants'] = [{'athlete': {'id': '2001' if home else '1001'}}]
            row['text'] = 'Synthetic Player makes free throw 1 of 2'
    ref = espn.scoreboard(scoreboard(payload), datetime(2026, 10, 13).date())[0]
    clean = espn.summary(payload, ref, datetime(2026, 10, 14, 10, tzinfo=timezone.utc))
    assert clean.pbp_usable
    plays = list(clean.plays)
    index = next(i for i, p in enumerate(plays) if p.period == 3 and p.scorer_name == 'Synthetic Player 2001') + 1
    extra = plays[index-1].model_copy(update={'external_id': ref.external_id + '999', 'free_throw_attempt': 2})
    plays.insert(index, extra)
    primary = clean.model_copy(update={'plays': tuple(p.model_copy(update={
        'index': i, 'home': p.home + (i >= index)}) for i,p in enumerate(plays))})
    jump = extra.model_copy(update={'scoring': False, 'points': 0,
        'free_throw_attempt': None, 'jump_ball_players': ('Synthetic Player 2001', 'Synthetic Player 1001')})
    backup_plays = list(clean.plays)
    backup_plays.insert(index, jump)
    backup = clean.model_copy(update={'provider': 'cbs', 'external_id': '50000001',
        'ref': clean.ref.model_copy(update={'provider': 'cbs', 'external_id': clean.ref.cbs_abbr}),
        'plays': tuple(p.model_copy(update={'index': i, 'external_id': None}) for i,p in enumerate(backup_plays))})
    return assess(primary), assess(backup), clean


def test_unique_corroborated_action_recovers_without_mutating_either_input():
    primary, backup, clean = evidence_pair()
    before = primary.model_dump(), backup.model_dump()
    effective, proof = recover_free_throw(primary, backup)
    assert effective.pbp_usable and effective.box_usable
    assert trajectory_features(effective) == trajectory_features(clean)
    assert effective.plays[-1].home == clean.home.score
    assert proof['original_action']['points'] == 1
    assert proof['original_action']['free_throw_attempt'] == 2
    assert proof['original_action']['external_id'].endswith('999')
    assert len(effective.plays) == len(primary.plays)
    assert effective.plays[-1].reported_home == primary.home.score + 1
    assert (primary.model_dump(), backup.model_dump()) == before


@pytest.mark.parametrize('change', [
    'no_jump', 'wrong_jump_clock', 'wrong_jump_player', 'backup_missing_score',
    'backup_extra_score', 'wrong_attempt', 'partial_box', 'wrong_final',
    'wrong_period_totals', 'wrong_matchup', 'wrong_tip', 'wrong_player_box',
    'wrong_player_team', 'wrong_player_name', 'wrong_box_ft', 'additional_pbp_error',
    'missing_scorer', 'pending',
])
def test_incomplete_or_conflicting_corroboration_stays_unavailable(change):
    a, b, _ = evidence_pair()
    if change.startswith('no_jump') or change in ('wrong_jump_clock', 'wrong_jump_player'):
        b = b.model_copy(update={'plays': tuple(p.model_copy(update={
            'jump_ball_players': () if change == 'no_jump' else ('Someone Else',) if change == 'wrong_jump_player' else p.jump_ball_players,
            'remaining_ms': p.remaining_ms - 1000 if change == 'wrong_jump_clock' else p.remaining_ms,
        }) if p.jump_ball_players else p for p in b.plays)})
    elif change in ('backup_missing_score', 'backup_extra_score'):
        i = next(i for i,p in enumerate(b.plays) if p.scorer_name == 'Synthetic Player 2001' and p.scoring)
        plays = list(b.plays)
        if change == 'backup_missing_score': plays.pop(i)
        else: plays.insert(i, plays[i])
        b = b.model_copy(update={'plays': tuple(plays)})
    elif change == 'wrong_attempt':
        a = a.model_copy(update={'plays': tuple(p.model_copy(update={'free_throw_attempt': 1}) if p.free_throw_attempt == 2 else p for p in a.plays)})
    elif change == 'partial_box': a = a.model_copy(update={'box_errors': ('missing_player_minutes',)})
    elif change == 'wrong_final': b = b.model_copy(update={'home': b.home.model_copy(update={'score': 5})})
    elif change == 'wrong_period_totals': b = b.model_copy(update={'home': b.home.model_copy(update={'periods': (1,2,0,1)})})
    elif change == 'wrong_matchup': b = b.model_copy(update={'ref': b.ref.model_copy(update={'home': 'MEM'})})
    elif change == 'wrong_tip': b = b.model_copy(update={'ref': b.ref.model_copy(update={'scheduled_at': None})})
    elif change.startswith('wrong_player') or change == 'wrong_box_ft':
        field = {'wrong_player_box': {'statistics': {}}, 'wrong_player_team': {'team_id': '9'},
                 'wrong_player_name': {'name': 'Other'}, 'wrong_box_ft': {'statistics': {**b.players[1].statistics, 'FTM': 3}}}[change]
        b = b.model_copy(update={'players': tuple(p.model_copy(update=field) if p.name == 'Synthetic Player 2001' else p for p in b.players)})
    elif change == 'additional_pbp_error': a = a.model_copy(update={'pbp_errors': (*a.pbp_errors, 'clock_order')})
    elif change == 'missing_scorer': a = a.model_copy(update={'plays': tuple(p.model_copy(update={'scorer_name': None}) if p.scoring else p for p in a.plays)})
    elif change == 'pending': b = b.model_copy(update={'status': 'pending'})
    assert recover_free_throw(a, b) is None


def test_exact_profile_slug_supports_abbreviated_backup_names_without_fuzzy_matching():
    a, b, _ = evidence_pair()
    b = b.model_copy(update={'players': tuple(p.model_copy(update={
        'name': 'S. Player', 'profile_slug': 'synthetic-player-2001'
    }) if p.name == 'Synthetic Player 2001' else p for p in b.players)})
    assert recover_free_throw(a, b)
    b = b.model_copy(update={'players': tuple(p.model_copy(update={
        'profile_slug': 'someone-else'
    }) if p.name == 'S. Player' else p for p in b.players)})
    assert recover_free_throw(a, b) is None


@pytest.mark.parametrize('change', ['primary_index', 'backup_index', 'jump_before_first', 'no_first_attempt'])
def test_action_order_and_free_throw_trip_must_be_established(change):
    a, b, _ = evidence_pair()
    if change == 'primary_index':
        a = a.model_copy(update={'plays': tuple(p.model_copy(update={'index': 999}) if p.free_throw_attempt == 2 else p for p in a.plays)})
    elif change == 'backup_index':
        b = b.model_copy(update={'plays': tuple(p.model_copy(update={'index': 999}) if p.jump_ball_players else p for p in b.plays)})
    elif change == 'jump_before_first':
        plays = list(b.plays)
        i = next(i for i,p in enumerate(plays) if p.jump_ball_players)
        plays[i-1], plays[i] = plays[i], plays[i-1]
        b = b.model_copy(update={'plays': tuple(p.model_copy(update={'index': i}) for i,p in enumerate(plays))})
    elif change == 'no_first_attempt':
        a = a.model_copy(update={'plays': tuple(p.model_copy(update={'free_throw_attempt': None}) if p.free_throw_attempt == 1 else p for p in a.plays)})
    assert recover_free_throw(a, b) is None
