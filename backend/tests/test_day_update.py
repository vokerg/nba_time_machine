"""Explicit job concurrency, cancellation, local access and opaque status."""
import asyncio
from datetime import date
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from nba_time_machine.api.day_update import local_access, router
from nba_time_machine.sports.day_update import DayUpdateJobs

DAY = date(2026, 10, 14)


@pytest.mark.asyncio
async def test_repeated_start_joins_job_and_other_dates_are_rejected():
    ready, release = asyncio.Event(), asyncio.Event()
    async def runner(factory, day, stage):
        stage("publishing")
        ready.set()
        await release.wait()
    profile = uuid4()
    jobs = DayUpdateJobs(None, runner)
    first = jobs.start(profile, DAY)
    try:
        await ready.wait()
        assert jobs.start(profile, DAY)["job_id"] == first["job_id"]
        assert jobs.status(profile, first["job_id"])["state"] == "publishing"
        assert jobs.status(uuid4(), first["job_id"]) is None
        with pytest.raises(ValueError):
            jobs.start(profile, date(2026, 10, 15))
        release.set()
        await jobs.task
        assert jobs.result["state"] == "finished"
        assert set(jobs.result) == {"job_id", "date", "state"}
    finally:
        await jobs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected", [(ValueError("secret body"), "update_failed"),
    (RuntimeError("secret database URL"), "update_failed"),
    (ValueError("sources_unavailable"), "sources_unavailable")])
async def test_error_messages_never_serialize_source_or_exception_bodies(failure, expected):
    async def runner(*args):
        raise failure
    jobs = DayUpdateJobs(None, runner)
    jobs.start(uuid4(), DAY)
    await jobs.task
    assert jobs.result["state"] == "failed" and jobs.result["error"] == expected
    assert "secret" not in str(jobs.result)


@pytest.mark.asyncio
async def test_timeout_and_shutdown_cancel_and_await_job():
    stopped = asyncio.Event()
    async def runner(*args):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    jobs = DayUpdateJobs(None, runner, timeout=.01)
    jobs.start(uuid4(), DAY)
    await jobs.task
    assert jobs.result["error"] == "update_time_limit" and stopped.is_set()
    stopped.clear()
    jobs.start(uuid4(), DAY)
    await asyncio.sleep(0)
    await jobs.close()
    assert stopped.is_set() and jobs.result["error"] == "update_interrupted"


def request(host="localhost:5173", client="127.0.0.1", origin=None):
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "scheme": "http", "path": "/", "query_string": b"",
                    "server": ("127.0.0.1", 8000), "client": (client, 1000), "headers": headers})


def test_local_gate_supports_vite_proxy_and_rejects_remote_or_cross_origin():
    from fastapi import HTTPException
    local_access(request(origin="http://localhost:5173"))
    for req in (request(client="192.0.2.1"), request(host="evil.test"), request(origin="https://evil.test")):
        with pytest.raises(HTTPException) as error:
            local_access(req)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_http_rejects_missing_action_header_before_database_lookup_and_hides_other_profiles():
    app = FastAPI()
    app.include_router(router)
    jobs = DayUpdateJobs(None)
    app.state.day_updates = jobs
    profile, job = uuid4(), uuid4()
    jobs.profile_id = profile
    jobs.result = {"job_id": str(job), "date": DAY.isoformat(), "state": "publishing"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)), base_url="http://localhost") as client:
        payload = {"date": DAY.isoformat(), "mode": "browse", "time_cursor": "2026-10-14T00:00:00Z"}
        assert (await client.post(f"/profiles/{profile}/guide/update", json=payload)).status_code == 403
        assert (await client.post(f"/profiles/{profile}/guide/update", json={**payload, "date": "2099-10-14"}, headers={"X-Guide-Action": "update-day"})).status_code == 422
        assert (await client.post(f"/profiles/{profile}/guide/update", json={**payload, "mode": "time-machine"})).status_code == 422
        result = await client.get(f"/profiles/{profile}/guide/update/{job}")
        assert result.status_code == 200 and result.json() == jobs.result
        assert result.headers["cache-control"] == "no-store"
        assert (await client.get(f"/profiles/{uuid4()}/guide/update/{job}")).status_code == 404
        assert (await client.get(f"/profiles/{profile}/guide/update/{job}", headers={"Origin":"https://evil.test"})).status_code == 403


@pytest.mark.asyncio
async def test_explicit_recalculation_uses_saved_evidence_without_collection(monkeypatch):
    from nba_time_machine.sports import day_update
    calls = []
    async def collect(*args):
        raise AssertionError('recalculation must not collect')
    async def process(factory, day, *, as_of):
        calls.append((day, as_of))
        return {'games': 1, 'eligible': 1, 'unavailable': 0, 'failed': 0}
    monkeypatch.setattr(day_update, 'process_stored_day', process)
    jobs = DayUpdateJobs(None, runner=collect)
    result = jobs.start(uuid4(), DAY, fetch=False)
    assert result['state'] == 'publishing'
    await jobs.task
    assert jobs.result['state'] == 'finished'
    assert len(calls) == 1 and calls[0][0] == DAY
