"""Disposable PostgreSQL only: CI supplies DATABASE_URL without .env loading."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, RawCaptureRecord, SourceOutcomeRecord, SourceRecord,
    TemporalFactRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.sports.collection import SportsCollector
from nba_time_machine.sports.errors import SportsProviderResponseError


@pytest.mark.integration
@pytest.mark.asyncio
async def test_collection_replay_changes_partial_stats_and_historical_availability(monkeypatch):
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip('disposable DATABASE_URL not configured')
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    event_id = str(uuid4())
    event = dict(idEvent=event_id, idLeague='4387', strSeason='2025-2026',
                 idHomeTeam=str(uuid4()), strHomeTeam='Home', idAwayTeam=str(uuid4()), strAwayTeam='Away',
                 strTimestamp='2025-10-21T23:00:00Z', strStatus='FT', intHomeScore='100', intAwayScore='90')
    class Client:
        async def season_events(self, season):
            return [event, dict(event, idEvent=str(uuid4()), strSeason='2026-2027')]
        async def events_on_date(self, day):
            raise SportsProviderResponseError('unavailable')
        async def event_stats(self, external):
            return [dict(idEvent=external, strStat='Points', intHome='100', intAway='90', secret='discard'),
                    dict(idEvent='wrong-game', strStat='Points', intHome='999', intAway='999')]
    async def no_sleep(_):
        pass
    monkeypatch.setattr('nba_time_machine.sports.collection.asyncio.sleep', no_sleep)
    try:
        async with factory.begin() as session:
            source = await session.get(SourceRecord, 'thesportsdb-nba')
            if source is None:
                session.add(SourceRecord(id='thesportsdb-nba', name='TheSportsDB NBA', kind='structured',
                                         adapter='thesportsdb', category=[], locator='https://www.thesportsdb.com/api/v1/json',
                                         enabled=False, verification_status='verified', cadence_minutes=10,
                                         requires_auth=False, retention_policy='normalized_full'))
        async def collect():
            return await SportsCollector(factory, Client(), manual=True).collect('2025-2026',
                        start=date(2025, 10, 21), end=date(2025, 10, 21), statistics=True)
        first = await collect()
        replay = await collect()
        event['intHomeScore'] = '101'
        correction = await collect()
        assert first.observations_written == first.stats_written == 1
        assert replay.observations_written == replay.stats_written == 0
        assert correction.observations_written == 1
        assert first.failed_requests == 1 and first.rejected == 2
        assert not first.complete_season_verified
        async with factory() as session:
            from nba_time_machine.db import SportsExternalIdentityRecord
            game_id = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                SportsExternalIdentityRecord.external_id == event_id))
            rows = list((await session.scalars(select(GameObservationRecord).where(
                GameObservationRecord.game_id == game_id).order_by(GameObservationRecord.observed_at))).all())
            assert len(rows) == 2
            assert [o.home_score for o in rows] == [100, 101]
            assert all(o.available_at == o.observed_at > o.scheduled_tip_at and o.final_at is None for o in rows)
            captures = list((await session.scalars(select(RawCaptureRecord).where(
                RawCaptureRecord.external_id.in_(['event:' + event_id, 'event_stats:' + event_id])))).all())
            assert len(captures) == 3
            assert all(c.raw_payload is None for c in captures)
            fact = await session.scalar(select(TemporalFactRecord).where(TemporalFactRecord.game_id == game_id))
            # Check the retained fields directly: a randomly generated event
            # UUID may legitimately contain the substring "999".
            assert fact.value == {'statistics': [
                {'idEvent': event_id, 'strStat': 'Points', 'intHome': '100', 'intAway': '90'},
            ]}
            outcome = await session.scalar(select(SourceOutcomeRecord).where(
                SourceOutcomeRecord.collection_run_id == first.run_id))
            assert outcome.status == 'partial'
            assert outcome.outcome_metadata['failed_requests'] == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_overlapping_jobs_fail_before_provider_requests():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip('disposable DATABASE_URL not configured')
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    from sqlalchemy import text
    class NoNetwork:
        async def season_events(self, season):
            pytest.fail('overlapping job requested provider data')
    try:
        async with factory() as session:
            assert await session.scalar(text('SELECT pg_try_advisory_lock(734387)'))
            try:
                with pytest.raises(ValueError, match='already running'):
                    await SportsCollector(factory, NoNetwork(), manual=True).collect('2026-2027')
            finally:
                await session.execute(text('SELECT pg_advisory_unlock(734387)'))
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_budget_exhaustion_is_durable_and_lock_is_released():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip('disposable DATABASE_URL not configured')
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    class BudgetClient:
        async def season_events(self, season):
            return []
        async def events_on_date(self, day):
            pytest.fail('budget exhausted before daily request')
    try:
        first = await SportsCollector(factory, BudgetClient(), manual=True, max_requests=1).collect(
            '2025-2026', start=date(2025, 10, 1), end=date(2025, 10, 2))
        assert first.requests == 1 and first.last_completed_date is None
        assert any('budget exhausted' in gap for gap in first.gaps)
        async with factory() as session:
            outcome = await session.scalar(select(SourceOutcomeRecord).where(
                SourceOutcomeRecord.collection_run_id == first.run_id))
            assert outcome.finished_at is not None
            assert outcome.outcome_metadata['gaps'] == first.gaps
        # A second invocation in the same process obtains the lock again.
        second = await SportsCollector(factory, BudgetClient(), manual=True, max_requests=1).collect('2026-2027')
        assert second.requests == 1
    finally:
        await engine.dispose()
