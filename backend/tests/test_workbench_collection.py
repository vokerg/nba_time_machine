"""Synthetic operator-action tests; no provider calls or owner database writes."""
import asyncio
from datetime import date

import httpx
import pytest

from nba_time_machine.main import app as consumer
from nba_time_machine.workbench.app import app
from nba_time_machine.workbench import collection
from nba_time_machine.sports.morning import GameResult, MorningReport
from nba_time_machine.sports.morning_models import GameRef


@pytest.mark.asyncio
async def test_single_job_failure_redaction_and_recovery(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    async def fake(factory, day):
        entered.set()
        await release.wait()
        raise RuntimeError('secret source body database password')
    monkeypatch.setattr(collection, 'collect_day', fake)
    job = collection.DayVerification(None)
    assert job.start(date(2026, 10, 16))
    await entered.wait()
    assert not job.start(date(2026, 10, 17))
    release.set()
    await job.task
    assert job.result['error'] == 'collection_failed'
    assert 'secret' not in str(job.result)
    assert job.start(date(2026, 10, 17))
    await job.close()


@pytest.mark.asyncio
async def test_routes_require_explicit_action_and_isolate_consumer(monkeypatch):
    release = asyncio.Event()
    async def process(factory, day, *, as_of):
        return {'games': 1, 'eligible': 1, 'unavailable': 0, 'failed': 0}
    monkeypatch.setattr(collection, 'process_stored_day', process)
    async def fake(factory, day):
        await release.wait()
        return {'games': [], 'errors': [], 'discovery': 'espn'}
    monkeypatch.setattr(collection, 'collect_day', fake)
    job = collection.DayVerification(None)
    monkeypatch.setattr(app.state, 'verification', job, raising=False)
    transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 1))
    body = {'slate_date': '2026-10-16'}
    headers = {'X-Workbench-Action': 'collect-day'}
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8765') as client:
        assert (await client.get('/api/verify')).json() == {'state': 'idle'}
        assert job.task is None
        assert (await client.post('/api/verify', json=body)).status_code == 403
        assert (await client.post('/api/verify', json=body, headers={**headers, 'Origin': 'https://evil.example'})).status_code == 403
        assert (await client.post('/api/verify', json={**body, 'write_scores': True}, headers=headers)).status_code == 422
        assert (await client.post('/api/verify', json={'slate_date': 'not a date'}, headers=headers)).status_code == 422
        response = await client.post('/api/verify', json=body, headers=headers)
        assert response.status_code == 202 and response.json()['state'] == 'running'
        job_id = response.json()['job_id']
        assert (await client.get('/api/verify', params={'job_id': job_id})).status_code == 200
        assert (await client.get('/api/verify?job_id=11111111-1111-4111-8111-111111111111')).status_code == 409
        assert (await client.post('/api/verify', json=body, headers=headers)).status_code == 409
        release.set()
        await job.task
        assert (await client.get('/api/verify')).json()['state'] == 'finished'
        assert (await client.post('/api/publish', json=body)).status_code == 403
        assert (await client.post('/api/publish', json=body, headers=headers)).status_code == 202
        await job.task
        assert job.result['ratings']['eligible'] == 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=consumer), base_url='http://test') as client:
        assert (await client.post('/api/verify', json=body, headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_collection_retains_pending_and_incomplete_and_bounds(monkeypatch):
    day = date(2026, 10, 16)
    report = MorningReport(day, collection.datetime.now(collection.timezone.utc), discovery='espn')
    report.games = [GameResult(GameRef(provider='espn', external_id='1', day=day, home='BOS', away='NYK', final=False)),
                    GameResult(GameRef(provider='espn', external_id='2', day=day, home='DET', away='WAS', final=True))]
    report.errors = ['espn_game_failed:2']
    report.persistence_errors = ['espn:persist_failed']
    class Store:
        def __init__(self, factory, *, manual):
            assert manual is True
        async def collect(self, collector, requested):
            assert requested == day
            assert collector.max_games == 20 and collector.client.max_requests == 40
            return report
    monkeypatch.setattr(collection, 'MorningStore', Store)
    result = await collection.collect_day(None, day)
    assert [g['status'] for g in result['games']] == ['pending', 'incomplete']
    assert result['games'][0]['pbp_provider'] is None
    assert result['errors'] == ['espn_game_failed:2', 'espn:persist_failed']
    assert 'evidence' not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['morning_source_policy_not_ready', 'sports_collection_already_running'])
async def test_policy_and_cross_process_busy_are_visible(monkeypatch, code):
    async def fake(*args):
        raise ValueError(code)
    monkeypatch.setattr(collection, 'collect_day', fake)
    job = collection.DayVerification(None)
    job.start(date(2026, 10, 16))
    await job.task
    assert job.result['error'] == code


@pytest.mark.asyncio
async def test_timeout_and_shutdown_are_terminal(monkeypatch):
    async def timeout(*args):
        raise TimeoutError()
    monkeypatch.setattr(collection, 'collect_day', timeout)
    job = collection.DayVerification(None)
    job.start(date(2026, 10, 16))
    await job.task
    assert job.result['error'] == 'collection_time_limit'
    entered = asyncio.Event()
    async def wait(*args):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(collection, 'collect_day', wait)
    job.start(date(2026, 10, 16))
    await entered.wait()
    await job.close()
    assert job.result['error'] == 'collection_interrupted'
    assert job.task.done()
