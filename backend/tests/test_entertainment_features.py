"""Synthetic box/PBP evidence and reproducible entertainment-candidate arithmetic."""
import pytest
from pydantic import ValidationError

from test_morning_features import evidence
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.ranking.entertainment_features import entertainment_measurements
from nba_time_machine.sports.morning_models import Play, assess
from nba_time_machine.workbench.app import CANDIDATE_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig, candidate_preview
from nba_time_machine.workbench.enrichment import PlayerSettings, PatternSettings, enrichment_preview


def candidate():
    return TuningConfig.model_validate_json(CANDIDATE_CONFIG.with_name('entertainment-preview-v2.json').read_text())


def game(home=(30, 30, 20, 20), away=(10, 10, 20, 20)):
    """Generate source-identified, reconcilable scoring actions, not NBA source content."""
    e = evidence()
    plays, scores = [], [0, 0]
    def add(period, remaining, **extra):
        plays.append(Play(external_id=f'synthetic-{len(plays)}', index=len(plays),
            period=period, remaining_ms=remaining, home=scores[0], away=scores[1], kind='synthetic', **extra))
    for period, (h, a) in enumerate(zip(home, away), 1):
        duration = 720000 if period <= 4 else 300000
        add(period, duration)
        total = h + a
        for side in [0] * h + [1] * a:
            scores[side] += 1
            count = sum(scores) - sum(home[:period - 1]) - sum(away[:period - 1])
            add(period, duration - int(duration * count / (total + 1)), scoring=True, points=1)
        add(period, 0, period_end=True, game_end=period == len(home))
    players = []
    for p in e.players:
        score = sum(home) if p.team_id == e.home.external_id else sum(away)
        stats = {k: 0 for k in p.statistics}
        stats.update(PTS=score, FTM=score, FTA=score, REB=1, DREB=1)
        players.append(p.model_copy(update={'statistics': stats}))
    return assess(e.model_copy(update={'plays': tuple(plays), 'players': tuple(players),
        'home': e.home.model_copy(update={'score': sum(home), 'periods': home}),
        'away': e.away.model_copy(update={'score': sum(away), 'periods': away})}))


def test_directional_extremes_not_exact_example_triggers():
    e = game()
    assert e.pbp_usable and e.box_usable
    measurements = entertainment_measurements(e)
    patterns = {p['signal']: p for p in measurements.patterns}
    assert patterns['first_half_lead']['raw'] == 50
    assert patterns['max_lead']['raw'] >= 40
    assert patterns['low_quarter']['raw'] == 10
    assert patterns['quarter_margin']['raw'] == 20
    assert all(p['source_play_ids'] for p in patterns.values())
    preview = enrichment_preview(measurements, PlayerSettings(), PatternSettings())
    assert preview['pattern_bonus']['points'] == 3
    assert all(0 <= p['normalized'] <= 1 for p in preview['patterns'])
    assert preview['historical_rarity'] is None
    # Nearby values also affect the ramp; no exact '-40' conditional.
    nearby = enrichment_preview(entertainment_measurements(game(home=(21, 21, 20, 20))), PlayerSettings(), PatternSettings())
    assert 0 < nearby['pattern_bonus']['groups']['dominance'] < 1


def test_zero_quarter_and_long_drought_are_valid_not_missing():
    e = game(home=(0, 30, 30, 30), away=(10, 10, 10, 10))
    m = entertainment_measurements(e)
    rows = {p['signal']: p for p in m.patterns}
    assert rows['low_quarter']['raw'] == 0
    assert rows['scoring_drought']['raw'] >= 720000
    assert rows['scoring_drought']['end_elapsed_ms'] - rows['scoring_drought']['start_elapsed_ms'] == rows['scoring_drought']['raw']
    p = enrichment_preview(m, PlayerSettings(), PatternSettings())
    assert next(x for x in p['patterns'] if x['signal'] == 'low_quarter')['normalized'] == 1


def test_regulation_quarters_exclude_short_overtime_periods():
    e = game(home=(20, 20, 20, 20, 2), away=(20, 20, 20, 20, 0))
    assert e.pbp_usable
    rows = {p['signal']: p for p in entertainment_measurements(e).patterns}
    assert rows['low_quarter']['raw'] == rows['high_quarter']['raw'] == 20
    assert rows['low_quarter']['period'] <= 4


def test_box_and_trajectory_failures_are_independent():
    e = game()
    missing_box = entertainment_measurements(e.model_copy(update={'players': ()}))
    assert missing_box.players is None and missing_box.patterns is not None
    partial_pbp = entertainment_measurements(e.model_copy(update={'pbp_errors': ('score_regression',)}))
    assert partial_pbp.players is not None and partial_pbp.patterns is None
    assert 'score_regression' in partial_pbp.pattern_errors
    pending = entertainment_measurements(e.model_copy(update={'status': 'pending'}))
    assert pending.players is pending.patterns is None


@pytest.mark.parametrize('stat,value', [('FGA', -1), ('FTM', 10000), ('REB', 7), ('AST', True)])
def test_malformed_box_counts_do_not_become_performance(stat, value):
    e = game()
    p = e.players[0]
    bad = p.model_copy(update={'statistics': {**p.statistics, stat: value}})
    result = entertainment_measurements(e.model_copy(update={'players': (bad, *e.players[1:])}))
    assert result.players is None
    assert 'inconsistent_player_box_statistics' in result.player_errors
    assert result.patterns is not None


def test_undefined_efficiency_dnp_and_rounded_minutes_are_explicit():
    e = game(home=(0, 0, 0, 0), away=(10, 10, 10, 10))
    rows = entertainment_measurements(e).players
    zero = next(p for p in rows if p['statistics']['PTS'] == 0)
    assert zero['true_shooting'] is None
    assert zero['minutes_precision'] == e.players[0].minutes_precision
    dnp = e.players[0].model_copy(update={'external_id': 'bench', 'did_not_play': True, 'statistics': {}, 'minutes': None})
    result = entertainment_measurements(e.model_copy(update={'players': (*e.players, dnp)}))
    assert result.players is not None and len(result.players) == len(rows)


def test_candidate_bonus_can_credit_a_one_sided_game_without_dilution():
    e = game()
    metrics = trajectory_features(e)
    m = entertainment_measurements(e)
    legacy = candidate_preview(metrics, m, TuningConfig.model_validate({k:v for k,v in candidate().model_dump().items() if k not in ('player','pattern')} | {'schema_version': 1}))
    enriched = candidate_preview(metrics, m, candidate())
    assert enriched['score'] > legacy['score']
    assert enriched['drama_score'] == legacy['score']
    assert enriched['player_bonus'] <= candidate().player.max_bonus
    assert enriched['pattern_bonus'] <= candidate().pattern.max_bonus
    assert enriched['score'] == round(enriched['drama_score'] + enriched['player_bonus'] + enriched['pattern_bonus'] + enriched['cap_adjustment'] + enriched['rounding_adjustment'], 4)


def test_missing_player_family_is_partial_never_fake_zero():
    e = game()
    m = entertainment_measurements(e.model_copy(update={'players': ()}))
    result = candidate_preview(trajectory_features(e), m, candidate())
    assert result['player_bonus'] is None
    assert result['coverage'] == 'partial'
    assert result['enrichment']['players'] is None


def test_correlated_patterns_use_maxima_and_score_is_capped():
    e = game()
    cfg = candidate()
    raw = cfg.model_dump()
    raw['player']['max_bonus'] = raw['pattern']['max_bonus'] = 10
    result = candidate_preview(trajectory_features(e), entertainment_measurements(e), TuningConfig.model_validate(raw))
    assert result['score'] == 10 and result['cap_adjustment'] < 0
    assert result['enrichment']['pattern_bonus']['normalized'] <= 1
    # Duplicate players do not accumulate unbounded bonuses: only top two count.
    m = entertainment_measurements(e)
    repeated = type(m)(players=m.players * 10, patterns=m.patterns, player_errors=(), pattern_errors=())
    p = enrichment_preview(repeated, PlayerSettings(), PatternSettings())
    assert p['player_bonus']['points'] <= 4 and len(p['player_bonus']['player_ids']) <= 2


@pytest.mark.parametrize('group,key,value', [
    ('player','points_peak',10), ('player','max_bonus',11), ('player','turnover_scale',0),
    ('pattern','first_half_lead_peak',5), ('pattern','low_quarter_ceiling',0),
    ('pattern','max_bonus',float('nan')),
])
def test_invalid_tuning_bounds_rejected(group,key,value):
    raw = candidate().model_dump()
    raw[group][key] = value
    with pytest.raises(ValidationError):
        TuningConfig.model_validate(raw)


def test_correlated_subthreshold_anomalies_do_not_add_three_times():
    from dataclasses import replace
    measured = entertainment_measurements(game())
    values = {'max_lead': 32, 'first_half_lead': 20, 'quarter_margin': 22,
              'low_quarter': 15, 'high_quarter': 35, 'scoring_drought': 240000}
    measured = replace(measured, patterns=tuple({**p, 'raw': values[p['signal']]} for p in measured.patterns))
    result = enrichment_preview(measured, PlayerSettings(), PatternSettings())
    assert result['pattern_bonus']['groups']['dominance'] == pytest.approx(.3)
    assert result['pattern_bonus']['points'] == pytest.approx(.9)
