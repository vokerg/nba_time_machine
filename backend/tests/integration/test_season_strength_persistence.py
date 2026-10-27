"""Verified prior evidence, cutoff isolation, publication and durable collection."""
from datetime import date, datetime, timedelta, timezone
import json
from itertools import count
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy import select, func, delete

from integration.test_morning_persistence import setup, FixtureCollector
from test_game_records import evidence_with_records
from test_season_strength import payloads
from nba_time_machine.db import (SeasonRecord, SportsExternalIdentityRecord, TemporalFactRecord,
                                 SourceRecord, RecommendationScoreRecord)
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.ranking.scoring import SEASON_STRENGTH_VERSION, WATCHABILITY_VERSION
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.season_foundation import FACT_TYPE, parse_foundation
from nba_time_machine.sports.season_foundation_store import ensure_foundation
from nba_time_machine.workbench.service import inspect_ratings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
TIP = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)
KNOWN = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAYS = count(15)
AFTER = TIP + timedelta(hours=4)


@pytest_asyncio.fixture(autouse=True)
async def isolated_season_schema(monkeypatch):
    # These tests share a season-level prior; isolate it from other fixtures and
    # previous runs rather than changing another test's source facts or policy.
    from nba_time_machine.db import DatabaseSettings, create_database_engine
    from nba_time_machine.db.models import Base
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip('disposable DATABASE_URL not configured')
    url = make_url(settings.application_sqlalchemy_url())
    if url.host not in ('localhost', '127.0.0.1', 'postgres'):
        pytest.skip('only disposable local/CI PostgreSQL permitted')
    schema = 'season_strength_' + uuid4().hex
    admin = create_database_engine(settings)
    async with admin.begin() as connection:
        await connection.execute(CreateSchema(schema))
    monkeypatch.setenv('DATABASE_URL', url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False))
    isolated = create_database_engine(DatabaseSettings(_env_file=None))
    try:
        async with isolated.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield
    finally:
        await isolated.dispose()
        async with admin.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def seed_game(factory):
    e = evidence_with_records(str(uuid4().int)[:12])
    tip = TIP.replace(day=next(DAYS))
    e = e.model_copy(update={'season': '2026-2027', 'observed_at': AFTER,
        'ref': e.ref.model_copy(update={'day': tip.date(), 'scheduled_at': tip})})
    assert (await MorningStore(factory, manual=True).collect(FixtureCollector([e]), tip.date())).captures_written == 1
    async with factory() as session:
        gid = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == 'espn', SportsExternalIdentityRecord.entity_type == 'game',
            SportsExternalIdentityRecord.external_id == e.external_id))
    return gid, e


async def seed_prior(factory, evidence, observed=KNOWN):
    a, b = payloads()
    # Bind synthetic prior rows to the canonical provider IDs from this matchup.
    ids = {evidence.home.abbreviation: evidence.home.external_id, evidence.away.abbreviation: evidence.away.external_id}
    for child in a['children']:
        for row in child['standings']['entries']:
            row['team']['id'] = ids.get(row['team']['abbreviation'], row['team']['id'])
    prior = parse_foundation(a, b, '2025-2026', KNOWN)
    async with factory.begin() as session:
        season = await session.scalar(select(SeasonRecord).where(SeasonRecord.league == 'NBA', SeasonRecord.label == prior.season))
        if season is None:
            season = SeasonRecord(league='NBA', label=prior.season)
            session.add(season)
            await session.flush()
        fact = TemporalFactRecord(subject_type='season', season_id=season.id, source_id='espn-nba-games',
            fact_type=FACT_TYPE, value=prior.model_dump(mode='json'), observed_at=observed,
            available_at=observed, valid_from=observed)
        session.add(fact)
        await session.flush()
        return fact.id


async def test_prior_is_shared_and_saved_v4_is_not_changed_until_explicit_publication():
    engine, factory = await setup()
    try:
        gid, e = await seed_game(factory)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(gid, as_of=AFTER, write=True)
        await seed_prior(factory, e)
        async with factory() as session:
            old = (await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,), as_of=AFTER))[0]
            assert old.model_version == WATCHABILITY_VERSION
            expected = (await MorningRankingPipeline(session).expectations((gid,), as_of=AFTER))[str(gid)]
            assert expected['model'] == 'pregame-records-v2'
            assert expected['basis'] == 'reconstructed'  # current records reconstructed after final
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(gid, as_of=AFTER+timedelta(minutes=1), write=True)
        async with factory() as session:
            scores = await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,), as_of=AFTER+timedelta(minutes=1))
            assert scores[0].model_version == SEASON_STRENGTH_VERSION
            part = next(p for p in scores[0].components if p.signal == 'matchup_expectation')
            assert part.weighted_contribution == pytest.approx(expected['overall_points'], abs=.0001)
            saved = next(g for g in (await inspect_ratings(session, e.ref.day, AFTER+timedelta(minutes=1)))['games'] if g['game_id'] == str(gid))
            assert saved['context']['home']['prior']['season'] == '2025-2026'
            assert saved['context']['calculation']['home_prior_weight'] > 0
            assert (await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((gid,), as_of=AFTER))[0] == old
    finally:
        async with factory.begin() as session:
            await session.execute(delete(TemporalFactRecord).where(TemporalFactRecord.fact_type == FACT_TYPE))
        await engine.dispose()


@pytest.mark.parametrize('fault', ['late_for_tip', 'late_validity', 'future_cutoff', 'expired', 'malformed', 'identity', 'ambiguous', 'wrong_season'])
async def test_prior_reader_withholds_invalid_or_unavailable_inputs(fault):
    engine, factory = await setup()
    try:
        gid, e = await seed_game(factory)
        fid = await seed_prior(factory, e, observed=AFTER if fault == 'late_for_tip' else KNOWN)
        async with factory.begin() as session:
            fact = await session.get(TemporalFactRecord, fid)
            if fault == 'future_cutoff': fact.available_at = AFTER + timedelta(days=1)
            if fault == 'late_validity': fact.valid_from = e.ref.scheduled_at + timedelta(hours=1)
            if fault == 'expired': fact.valid_to = KNOWN + timedelta(seconds=1)
            if fault == 'malformed': fact.value = {'broken': True}
            if fault == 'identity':
                value = json.loads(json.dumps(fact.value))
                next(t for t in value['teams'] if t['team'] == e.home.abbreviation)['external_id'] = '999999'
                fact.value = value
            if fault == 'wrong_season': fact.value = {**fact.value, 'season': '2024-2025'}
            if fault == 'ambiguous': session.add(TemporalFactRecord(subject_type='season', season_id=fact.season_id,
                source_id=fact.source_id, fact_type=FACT_TYPE, value=fact.value, observed_at=fact.observed_at,
                available_at=fact.available_at, valid_from=fact.valid_from))
        async with factory() as session:
            values = await MorningRankingPipeline(session).expectations((gid,), as_of=AFTER)
            value = values.get(str(gid))
            if fault in ('late_for_tip', 'late_validity'):
                assert value['model'] == 'pregame-records-v2'  # retrospective Browse only
                # Test the same actual record context against the strict prior reader.
                pipeline = MorningRankingPipeline(session)
                await pipeline.derive_many((gid,), as_of=AFTER)
                batch = pipeline._loaded_batch[2]
                from nba_time_machine.ranking.game_records import game_record_context
                context = game_record_context(e)
                assert 'prior_provenance' not in await batch.strength_context(context, gid, AFTER, e.ref.scheduled_at, strict=True)
            else:
                assert value is None or value['model'] == 'pregame-records-v1'
    finally:
        async with factory.begin() as session:
            # Isolate this shared season-level fixture from the following case.
            await session.execute(delete(TemporalFactRecord).where(TemporalFactRecord.fact_type == FACT_TYPE))
        await engine.dispose()


async def test_explicit_collection_is_durable_once_per_season_and_deduplicates(monkeypatch):
    from nba_time_machine.sports import season_foundation_store as store
    engine, factory = await setup()
    calls = []
    standings, finals = payloads()
    async def fetch(self, provider, url, stage, game=None):
        calls.append(url)
        self.requests += 1
        return json.dumps(standings if 'standings?' in url else finals)
    monkeypatch.setattr(store.PublicNBAClient, 'fetch', fetch)
    try:
        async with factory.begin() as session:
            await session.execute(delete(TemporalFactRecord).where(TemporalFactRecord.fact_type == FACT_TYPE))
        result = await ensure_foundation(factory, TIP.date(), force=True)
        assert result['status'] == 'collected' and result['captures_written'] == 1
        # A new call/session uses PostgreSQL state, without another publisher request.
        assert (await ensure_foundation(factory, TIP.date()))['status'] == 'stored'
        assert len(calls) == 2
        assert (await ensure_foundation(factory, TIP.date(), force=True))['captures_written'] == 0
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(TemporalFactRecord).where(TemporalFactRecord.fact_type == FACT_TYPE)) == 1
    finally:
        async with factory.begin() as session:
            await session.execute(delete(TemporalFactRecord).where(TemporalFactRecord.fact_type == FACT_TYPE))
        await engine.dispose()


async def test_failed_foundation_has_durable_cooldown_and_no_body_leak(monkeypatch):
    from nba_time_machine.sports import season_foundation_store as store
    from nba_time_machine.db import CollectionRunRecord
    engine, factory = await setup()
    calls = []
    async def fail(self, *args, **kwargs):
        calls.append(True)
        self.requests += 1
        raise ValueError('secret provider body')
    monkeypatch.setattr(store.PublicNBAClient, 'fetch', fail)
    try:
        async with factory.begin() as session:
            await session.execute(delete(TemporalFactRecord).where(TemporalFactRecord.fact_type == FACT_TYPE))
        result = await ensure_foundation(factory, TIP.date(), force=True)
        assert result['status'] == 'unavailable' and result['error'] == 'standings_fetch_failed'
        assert 'secret' not in json.dumps(result)
        assert (await ensure_foundation(factory, TIP.date()))['status'] == 'cooldown'
        assert len(calls) == 1
        async with factory() as session:
            run = await session.scalar(select(CollectionRunRecord).where(CollectionRunRecord.collector_version == store.COLLECTOR)
                .order_by(CollectionRunRecord.started_at.desc()).limit(1))
            assert run.finished_at is not None and 'secret' not in json.dumps(run.run_metadata)
    finally:
        await engine.dispose()
