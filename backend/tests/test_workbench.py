"""Calculation parity and isolation of the separate local workbench."""
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from test_morning_features import evidence
from nba_time_machine.main import app as consumer_app
from nba_time_machine.ranking.morning_features import trajectory_features
from nba_time_machine.ranking.scoring import FeatureObservation, score_postgame
from nba_time_machine.workbench.app import app, DEFAULT_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig, preview, MISSING
from nba_time_machine.workbench.evidence import supporting_plays


def baseline():
    return TuningConfig.model_validate_json(DEFAULT_CONFIG.read_text())


def test_preview_reproduces_production_formula_and_components_sum():
    metrics = trajectory_features(evidence())
    output = preview(metrics, baseline())
    now = datetime.now(timezone.utc)
    production = score_postgame(uuid4(), {signal: FeatureObservation(value, 'fixture', now, now)
        for signal, value in metrics.normalized().items()}, final_at=now, as_of=now)
    assert output['score'] == production.value
    assert round(sum(p['score_contribution'] for p in output['signals']), 4) == production.value
    assert output['weight_denominator'] == 70
    assert {p['signal']: p['normalized'] for p in output['signals']} == {
        signal.value: value for signal, value in metrics.normalized().items()}


def test_preview_changes_do_not_mutate_baseline():
    original = baseline()
    value = original.model_dump()
    value['version'] = 'experiment-v1'
    value['weights']['clutch'] = 0
    metrics = trajectory_features(evidence())
    assert preview(metrics, TuningConfig.model_validate(value))['score'] == 0
    assert preview(metrics, original)['score'] > 0
    assert original.weights['clutch'] == 25


@pytest.mark.parametrize('mutation', [
    {'weights': {'clutch': 1}},
    {'weights': dict(clutch=0, lead_changes=0, comeback=0, overtime=0)},
    {'scales': dict(clutch=0, lead_changes=20, comeback=25, overtime=3)},
    {'weights': dict(clutch=float('nan'), lead_changes=15, comeback=20, overtime=10)},
    {'medium_from': 8, 'high_from': 7}, {'version': '../../unsafe'}, {'schema_version': 2},
    {'weights': dict(clutch=True, lead_changes=15, comeback=20, overtime=10)},
])
def test_invalid_configuration_rejected(mutation):
    with pytest.raises(ValidationError):
        TuningConfig.model_validate({**baseline().model_dump(), **mutation})


def test_supporting_events_and_missing_inventory():
    e = evidence()
    metrics = trajectory_features(e)
    events = supporting_plays(e, metrics)
    assert sum(p['clutch_ms'] for p in events) == metrics.clutch_ms
    assert sum('lead_changes' in p['tags'] for p in events) == metrics.lead_changes
    assert all(p['source_play_id'] for p in events)
    assert {'star_power', 'stakes', 'rarity', 'game_quality'} <= {m['signal'] for m in MISSING}


def test_supporting_lead_change_and_comeback_use_source_events():
    e = evidence()
    plays = list(e.plays)
    plays[1] = plays[1].model_copy(update={'home': 0, 'away': 1})
    e = e.model_copy(update={'plays': tuple(plays)})
    metrics = trajectory_features(e)
    events = supporting_plays(e, metrics)
    assert sum('lead_changes' in p['tags'] for p in events) == metrics.lead_changes == 1
    deficits = [p for p in events if 'comeback' in p['tags']]
    assert len(deficits) == 1 and deficits[0]['away'] - deficits[0]['home'] == metrics.winner_max_deficit


@pytest.mark.asyncio
async def test_loopback_host_origin_and_consumer_route_boundaries():
    local = httpx.ASGITransport(app=app, client=('127.0.0.1', 1234))
    async with httpx.AsyncClient(transport=local, base_url='http://127.0.0.1:8765') as client:
        response = await client.get('/')
        assert response.status_code == 200 and 'Scoring workbench' in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert (await client.get('/', headers={'Host': 'attacker.example'})).status_code == 403
        assert (await client.get('/', headers={'Origin': 'http://attacker.example'})).status_code == 403
        assert (await client.post('/api/preview', content='x' * 17000)).status_code == 413
    remote = httpx.ASGITransport(app=app, client=('203.0.113.1', 1234))
    async with httpx.AsyncClient(transport=remote, base_url='http://127.0.0.1:8765') as client:
        assert (await client.get('/')).status_code == 403
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=consumer_app), base_url='http://test') as client:
        assert (await client.get('/api/slate?date=2026-10-14')).status_code == 404
        assert (await client.get('/static/workbench.js')).status_code == 404
