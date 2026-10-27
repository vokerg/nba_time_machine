"""Admin details captured at explicit publication time, never rebuilt on reads."""
from dataclasses import asdict

from nba_time_machine.ranking.entertainment import PlayerSettings, PatternSettings, enrichment_preview
from nba_time_machine.ranking.entertainment_features import entertainment_measurements
from nba_time_machine.ranking.game_records import game_record_context
from nba_time_machine.ranking.pregame import RecordSettings, record_preview
from nba_time_machine.ranking.star_power import StarSettings, star_preview
from nba_time_machine.sports.morning_models import Evidence, assess


def saved_inspection(fact, metrics, snapshot):
    evidence = assess(Evidence.model_validate({**fact.value, 'observed_at': fact.observed_at}))
    return {
        'evidence_fact_id': str(fact.id),
        'metrics': asdict(metrics),
        'enrichment': enrichment_preview(entertainment_measurements(evidence), PlayerSettings(), PatternSettings()),
        'context': record_preview(game_record_context(evidence), RecordSettings()),
        'star_power': star_preview(evidence, snapshot, StarSettings()),
        'settings': {'player': PlayerSettings().model_dump(), 'pattern': PatternSettings().model_dump(),
                     'star': StarSettings().model_dump()},
        'diagnostics': list(evidence.pbp_errors),
        'box_diagnostics': list(evidence.box_errors),
        'provenance': {'fact_id': str(fact.id), 'source_id': fact.source_id,
                       'observed_at': fact.observed_at.isoformat(), 'available_at': fact.available_at.isoformat(),
                       'trajectory_basis': evidence.trajectory_basis},
    }
