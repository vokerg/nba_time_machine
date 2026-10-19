from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from test_game_records import evidence_with_records
from nba_time_machine.ranking.game_records import game_record_context
from nba_time_machine.ranking.pregame import expectation, RecordSettings, record_preview
from nba_time_machine.ranking.scoring import (FeatureObservation, PostgameSignal, score_postgame,
    add_matchup_expectation, score_evidence_is_consistent, component_points, OVERALL_VERSION)

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def test_shared_calculation_and_open_allowlist():
    context = game_record_context(evidence_with_records())
    # Strong entering records, independent of any particular game's result.
    for side in ('home', 'away'):
        context[side].update(wins=20, losses=5, games_played=25)
    value = expectation(context, source_ref='fact:1', observed_at=NOW, available_at=NOW)
    assert value['overall_points'] == record_preview(context, RecordSettings())['bonus']
    assert abs(value['rating'] / 5 - value['overall_points']) < .0001
    assert value['teams'][0]['wins'] == 20
    assert all('provider_after_wins' not in t and 'removed_result' not in t for t in value['teams'])
    assert value['basis'] == 'reconstructed' and value['coverage'] == 'records-only'
    context['home'].update(wins=0, losses=1, games_played=1)
    assert expectation(context, source_ref='fact:1', observed_at=NOW, available_at=NOW) is None


def test_additive_version_and_cap_are_reproducible_and_tampering_is_rejected():
    for drama in (0., .5, 1.):
        base = score_postgame(uuid4(), {PostgameSignal.CLUTCH: FeatureObservation(
            drama, 'fact:drama', NOW, NOW)}, final_at=NOW, as_of=NOW)
        overall = add_matchup_expectation(base, .8, source_ref='fact:records', observed_at=NOW, available_at=NOW)
        assert overall.model_version == OVERALL_VERSION
        assert overall.value == min(10, base.value + 1.6)
        assert score_evidence_is_consistent(overall)
        assert abs(sum(component_points(overall)) - overall.value) < .001
        assert not score_evidence_is_consistent(replace(overall, value=overall.value - .1))
        assert not score_evidence_is_consistent(replace(overall, components=overall.components + overall.components[-1:]))
        assert score_evidence_is_consistent(base)  # original archive unchanged
