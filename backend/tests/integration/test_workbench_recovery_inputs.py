"""Both canonical inputs must be eligible; preview cannot write or unlock ratings."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from integration.test_morning_persistence import setup, FixtureCollector, DAY, NOW
from test_workbench_recovery import evidence_pair
from nba_time_machine.db import (GameObservationRecord, SourceRecord,
    SportsExternalIdentityRecord, TemporalFactRecord, RawCaptureRecord,
    RecommendationScoreRecord)
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.workbench.app import DEFAULT_CONFIG, CANDIDATE_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig
from nba_time_machine.workbench.recovery import preview_recovery
from nba_time_machine.workbench.service import inspect_game

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def capture_pair(factory):
    a, b, clean = evidence_pair()
    season = 'recovery-' + str(uuid4())
    event = str(uuid4().int)[:15]
    a = a.model_copy(update={'season': season, 'external_id': event,
        'ref': a.ref.model_copy(update={'external_id': event}),
        'plays': tuple(p.model_copy(update={'external_id': event + str(p.index)}) for p in a.plays)})
    b = b.model_copy(update={'season': season, 'external_id': str(uuid4().int)[:15],
        'observed_at': NOW + timedelta(seconds=1)})
    store = MorningStore(factory, manual=True)
    assert (await store.collect(FixtureCollector([a]), DAY)).captures_written == 1
    assert (await store.collect(FixtureCollector([b]), DAY)).captures_written == 1
    async with factory() as session:
        game = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == 'espn',
            SportsExternalIdentityRecord.external_id == event))
    return game


async def latest_observation(session, game):
    return await session.scalar(select(GameObservationRecord).where(
        GameObservationRecord.game_id == game).order_by(GameObservationRecord.observed_at.desc()))


async def test_recovered_preview_is_read_only_and_production_remains_withheld():
    engine, factory = await setup()
    try:
        game = await capture_pair(factory)
        async with factory() as session:
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            models = (TemporalFactRecord, RawCaptureRecord, RecommendationScoreRecord)
            before = [await session.scalar(select(func.count()).select_from(m)) for m in models]
            observation = await latest_observation(session, game)
            report = await inspect_game(session, observation, NOW + timedelta(hours=1),
                TuningConfig.model_validate_json(DEFAULT_CONFIG.read_text()),
                TuningConfig.model_validate_json(CANDIDATE_CONFIG.read_text()))
            assert report['baseline'] and report['experiment']
            assert report['evidence']['pbp_errors']
            assert report['recovery']['effective_evidence']['pbp_errors'] == []
            assert {p['provider'] for p in report['recovery']['inputs']} == {'espn', 'cbs'}
            assert report['archived'] is None
            assert await MorningRankingPipeline(session).derive(game, as_of=NOW + timedelta(hours=1)) is None
            assert before == [await session.scalar(select(func.count()).select_from(m)) for m in models]
    finally:
        await engine.dispose()


@pytest.mark.parametrize('change', [
    'espn_revoked', 'cbs_revoked', 'espn_expired', 'cbs_expired',
    'espn_ambiguous_fact', 'cbs_ambiguous_fact', 'espn_ambiguous_observation',
    'cbs_ambiguous_observation', 'observation_mismatch', 'pending',
    'future_backup', 'unmapped', 'latest_partial',
])
async def test_latest_temporal_mapping_and_source_policy_guards(change):
    engine, factory = await setup()
    try:
        game = await capture_pair(factory)
        async with factory() as session:
            observation = await latest_observation(session, game)
            as_of = NOW + timedelta(hours=1)
            provider = 'espn' if change.startswith('espn') else 'cbs'
            source_id = SOURCE_IDS[provider]
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game, TemporalFactRecord.source_id == source_id,
                TemporalFactRecord.fact_type == 'provider_game_evidence'))
            if change.endswith('revoked'):
                (await session.get(SourceRecord, source_id)).verification_status = 'unverified'
            elif change.endswith('expired'): fact.valid_to = as_of
            elif change.endswith('ambiguous_fact'):
                session.add(TemporalFactRecord(subject_type='game', game_id=game,
                    source_id=source_id, fact_type=fact.fact_type, value=fact.value,
                    valid_from=fact.valid_from, observed_at=fact.observed_at, available_at=fact.available_at))
            elif change.endswith('ambiguous_observation'):
                obs = await session.scalar(select(GameObservationRecord).where(
                    GameObservationRecord.game_id == game, GameObservationRecord.source_id == source_id))
                fields = {c.name: getattr(obs, c.name) for c in obs.__table__.columns if c.name != 'id'}
                session.add(GameObservationRecord(**fields))
                # Ambiguous observations for one provider/time are prohibited
                # at the persistence boundary, unlike temporal evidence facts.
                with pytest.raises(IntegrityError):
                    await session.flush()
                await session.rollback()
                return
            elif change == 'observation_mismatch': observation.available_at += timedelta(seconds=1)
            elif change == 'pending': observation.status = 'in_progress'
            elif change == 'future_backup': as_of = NOW
            elif change == 'unmapped':
                row = await session.scalar(select(SportsExternalIdentityRecord).where(
                    SportsExternalIdentityRecord.game_id == game, SportsExternalIdentityRecord.provider_key == 'cbs'))
                await session.delete(row)
            elif change == 'latest_partial':
                fact.value = {**fact.value, 'plays': []}
            await session.flush()
            assert await preview_recovery(session, observation, as_of) is None
            await session.rollback()
    finally:
        await engine.dispose()
