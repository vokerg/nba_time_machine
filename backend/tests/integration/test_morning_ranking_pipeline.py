"""Capture -> reproducible features -> archived score -> gated coarse verdict."""
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import delete, select

from integration.test_morning_persistence import setup, evidence, FixtureCollector, DAY, NOW
from nba_time_machine.db import (
    RecommendationScoreRecord, SourceRecord, SportsExternalIdentityRecord, TemporalFactRecord,
)
from nba_time_machine.ranking.morning_pipeline import BUNDLE_TYPE, MorningRankingPipeline
from nba_time_machine.ranking.queries import SqlAlchemyPostgameScoreRepository
from nba_time_machine.ranking.disclosure import ranking_fields
from nba_time_machine.ranking.config import RankingDisclosureSettings
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.api.game_disclosure import router as disclosure_router
from nba_time_machine.temporal import TimelineService, SqlAlchemyTimelineRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def capture(factory, run_ids=None):
    e = evidence().model_copy(update={"season": "ranking-" + str(uuid4())})
    report = await MorningStore(factory, manual=True).collect(FixtureCollector([e]), DAY)
    assert report.captures_written == 1
    if run_ids is not None:
        run_ids.append(UUID(report.run_id))
    async with factory() as session:
        game = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == "espn",
            SportsExternalIdentityRecord.entity_type == "game",
            SportsExternalIdentityRecord.external_id == e.external_id))
    return game, e


async def test_dry_run_idempotent_materialization_and_temporal_visibility():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            pipeline = MorningRankingPipeline(session)
            assert not await pipeline.process(game, as_of=NOW - timedelta(seconds=1))
            assert await pipeline.process(game, as_of=cursor)
            assert not await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == game))
            assert await pipeline.process(game, as_of=cursor, write=True)
            assert await pipeline.process(game, as_of=cursor, write=True)
        async with factory() as session:
            bundles = (await session.scalars(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game, TemporalFactRecord.fact_type == BUNDLE_TYPE))).all()
            assert len(bundles) == 1
            assert bundles[0].value["metrics"]["clutch_ms"] == 300_000
            assert bundles[0].fact_metadata["actual_final_at"] is None
            assert bundles[0].observed_at == bundles[0].available_at == NOW
            reader = SqlAlchemyPostgameScoreRepository(session)
            assert await reader.postgame_scores_as_of((game,), as_of=NOW) == ()
            scores = await reader.postgame_scores_as_of((game,), as_of=cursor)
            assert len(scores) == 1 and len(scores[0].components) == 6
            assert scores[0].components[0].source_ref.endswith(bundles[0].fact_metadata["input_fact_id"])
            # Existing disclosure bridge emits coarse fields, never a numeric score.
            fields = ranking_fields(scores[0], bands=RankingDisclosureSettings().bands())
            assert fields and all(isinstance(f.value, str) for f in fields)
        profile = uuid4()
        async with factory() as session:
            await TimelineService(SqlAlchemyTimelineRepository(session)).initialize(profile, cursor)
        app = FastAPI()
        app.state.session_factory = factory
        app.include_router(disclosure_router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/profiles/{profile}/games/{game}/watchability")
            assert response.status_code == 200
            assert response.json() == {"game_id": str(game), "disclosure": "watchability",
                                       "watchability_verdict": "Worth considering"}
    finally:
        await engine.dispose()


async def test_new_partial_revision_masks_old_score_without_destroying_history():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
        corrected = e.model_copy(update={"observed_at": NOW + timedelta(hours=2),
            "pbp_errors": ("score_regression",)})
        await MorningStore(factory, manual=True).collect(FixtureCollector([corrected]), DAY)
        async with factory() as session:
            reader = SqlAlchemyPostgameScoreRepository(session)
            assert len(await reader.postgame_scores_as_of((game,), as_of=cursor)) == 1
            assert await reader.postgame_scores_as_of((game,), as_of=NOW + timedelta(hours=3)) == ()
            assert not await MorningRankingPipeline(session).process(game, as_of=NOW + timedelta(hours=3))
            assert await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == game)) is not None
    finally:
        await engine.dispose()


async def test_source_revocation_withholds_already_archived_rating():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=cursor, write=True)
            source = await session.get(SourceRecord, SOURCE_IDS["espn"])
            source.verification_status = "unverified"
        async with factory() as session:
            assert await SqlAlchemyPostgameScoreRepository(session).postgame_scores_as_of((game,), as_of=cursor) == ()
    finally:
        async with factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE_IDS["espn"])
            source.verification_status = "verified"
        await engine.dispose()


@pytest.mark.parametrize("fault", ["malformed", "identity", "expired", "ambiguous", "future"])
async def test_untrusted_latest_evidence_does_not_materialize(fault):
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        cursor = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game,
                TemporalFactRecord.fact_type == "provider_game_evidence"))
            if fault == "malformed":
                fact.value = {"broken": True}
            elif fault == "identity":
                fact.value = {**fact.value, "external_id": "unmapped-game"}
            elif fault == "expired":
                fact.valid_to = NOW + timedelta(minutes=1)
            elif fault == "future":
                fact.available_at = cursor + timedelta(minutes=1)
            else:
                session.add(TemporalFactRecord(subject_type="game", game_id=game,
                    source_id=fact.source_id, fact_type=fact.fact_type, value=fact.value,
                    observed_at=fact.observed_at, available_at=fact.available_at,
                    valid_from=fact.valid_from))
        async with factory.begin() as session:
            pipeline = MorningRankingPipeline(session)
            assert await pipeline.derive(game, as_of=cursor) is None
            assert (await pipeline.derive_many((game,), as_of=cursor))[game] is None
            assert not await pipeline.process(game, as_of=cursor, write=True)
            assert await session.scalar(select(RecommendationScoreRecord.id).where(
                RecommendationScoreRecord.game_id == game)) is None
    finally:
        await engine.dispose()


async def test_complete_revision_requires_new_snapshot_then_is_available():
    engine, factory = await setup()
    try:
        game, e = await capture(factory)
        before, after = NOW + timedelta(hours=1), NOW + timedelta(hours=3)
        async with factory.begin() as session:
            assert await MorningRankingPipeline(session).process(game, as_of=before, write=True)
        revised = e.model_copy(update={"observed_at": NOW + timedelta(hours=2),
                                      "notes": ("synthetic_revision",)})
        await MorningStore(factory, manual=True).collect(FixtureCollector([revised]), DAY)
        async with factory.begin() as session:
            reader = SqlAlchemyPostgameScoreRepository(session)
            assert await reader.postgame_scores_as_of((game,), as_of=after) == ()
            assert await MorningRankingPipeline(session).process(game, as_of=after, write=True)
            assert len(await reader.postgame_scores_as_of((game,), as_of=before)) == 1
            assert len(await reader.postgame_scores_as_of((game,), as_of=after)) == 1
            rows = (await session.scalars(select(RecommendationScoreRecord).where(
                RecommendationScoreRecord.game_id == game))).all()
            assert len(rows) == 2
    finally:
        await engine.dispose()


async def collect_tracked(factory, values, run_ids):
    report = await MorningStore(factory, manual=True).collect(FixtureCollector(values), DAY)
    run_ids.append(UUID(report.run_id))
    return report


async def cleanup_test_runs(factory, run_ids):
    # These uniquely tracked synthetic runs belong only to this test. Leaving
    # them behind can exhaust the operator's deliberately bounded health window.
    from nba_time_machine.db import CollectionRunRecord, RawCaptureRecord, SourceOutcomeRecord
    async with factory.begin() as session:
        await session.execute(delete(RawCaptureRecord).where(RawCaptureRecord.collection_run_id.in_(run_ids)))
        await session.execute(delete(SourceOutcomeRecord).where(SourceOutcomeRecord.collection_run_id.in_(run_ids)))
        await session.execute(delete(CollectionRunRecord).where(CollectionRunRecord.id.in_(run_ids)))


@pytest.mark.parametrize('fault', [None, 'new_partial_primary', 'expired', 'revoked',
                                   'ambiguous', 'conflicting_score', 'pending', 'conflicting_tip', 'conflicting_periods'])
async def test_partial_backup_preserves_only_current_agreeing_primary_trajectory(fault):
    from morning_fixtures import cbs_html
    from nba_time_machine.sports import cbs
    from nba_time_machine.db import GameObservationRecord
    engine, factory = await setup()
    run_ids = []
    try:
        game, e = await capture(factory, run_ids)
        # ESPN box may be incomplete while the trajectory remains usable.
        primary = e.model_copy(update={'observed_at': NOW + timedelta(minutes=1),
            'box_errors': ('missing_player_minutes_or_points',), 'notes': ('box_failure',)})
        await collect_tracked(factory, [primary], run_ids)
        if fault == 'new_partial_primary':
            bad = primary.model_copy(update={'observed_at': NOW + timedelta(minutes=2),
                'pbp_errors': ('score_regression',)})
            await collect_tracked(factory, [bad], run_ids)
        backup = cbs.gametracker(cbs_html(), e.ref, NOW + timedelta(minutes=3)).model_copy(
            update={'season': e.season, 'external_id': str(uuid4().int)[:12]})
        await collect_tracked(factory, [backup], run_ids)
        async with factory.begin() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game, TemporalFactRecord.source_id == SOURCE_IDS['espn'],
                TemporalFactRecord.observed_at == primary.observed_at))
            if fault == 'expired':
                fact.valid_to = NOW + timedelta(minutes=4)
            elif fault == 'revoked':
                source = await session.get(SourceRecord, SOURCE_IDS['espn'])
                source.verification_status = 'unverified'
            elif fault == 'ambiguous':
                session.add(TemporalFactRecord(subject_type='game', game_id=game,
                    source_id=fact.source_id, fact_type=fact.fact_type, value=fact.value,
                    observed_at=fact.observed_at, available_at=fact.available_at, valid_from=fact.valid_from))
            elif fault == 'conflicting_periods':
                backup_fact = await session.scalar(select(TemporalFactRecord).where(
                    TemporalFactRecord.game_id == game, TemporalFactRecord.source_id == SOURCE_IDS['cbs']))
                backup_fact.value = {**backup_fact.value, 'home': {**backup_fact.value['home'], 'periods': [0, 2, 1, 1]}}
            elif fault in ('conflicting_score', 'pending', 'conflicting_tip'):
                obs = await session.scalar(select(GameObservationRecord).where(
                    GameObservationRecord.game_id == game, GameObservationRecord.source_id == SOURCE_IDS['cbs']))
                if fault == 'conflicting_score':
                    obs.home_score += 1
                elif fault == 'pending':
                    obs.status = 'in_progress'
                else:
                    obs.scheduled_tip_at += timedelta(minutes=5)
        async with factory() as session:
            pipeline = MorningRankingPipeline(session)
            result = await pipeline.derive(game, as_of=NOW + timedelta(hours=1))
            batched = (await pipeline.derive_many((game,), as_of=NOW + timedelta(hours=1)))[game]
            assert batched == result
            assert (result is not None) == (fault is None)
            if result:
                assert result[0].source_id == SOURCE_IDS['espn']
                assert result[1].clutch_ms == 300000
            from nba_time_machine.workbench.service import inspect_game
            from nba_time_machine.workbench.calculations import TuningConfig
            from nba_time_machine.workbench.app import DEFAULT_CONFIG
            config = TuningConfig.model_validate_json(DEFAULT_CONFIG.read_text())
            obs = await session.scalar(select(GameObservationRecord).where(
                GameObservationRecord.game_id == game, GameObservationRecord.source_id == SOURCE_IDS['cbs']))
            inspected = await inspect_game(session, obs, NOW + timedelta(hours=1), config, config)
            assert {p['provider'] for p in inspected['provider_coverage']} == {'espn', 'cbs'}
    finally:
        if fault == 'revoked':
            async with factory.begin() as session:
                source = await session.get(SourceRecord, SOURCE_IDS['espn'])
                source.verification_status = 'verified'
        await cleanup_test_runs(factory, run_ids)
        await engine.dispose()


async def test_reconstructed_evidence_persists_original_claims_and_replays_idempotently():
    from nba_time_machine.sports.morning_models import assess, reconcile_score_states
    engine, factory = await setup()
    run_ids = []
    try:
        e = evidence().model_copy(update={'season': 'recovery-' + str(uuid4())})
        plays, previous = [], (0, 0)
        for p in e.plays:
            team = e.home.external_id if p.home > previous[0] else e.away.external_id
            plays.append(p.model_copy(update={'scoring_team_id': team if p.scoring else None}))
            previous = p.home, p.away
        plays[3] = plays[3].model_copy(update={'home': 0})
        recovered = reconcile_score_states(assess(e.model_copy(update={'plays': tuple(plays)})))
        assert recovered.trajectory_basis == 'scoring_actions_v1'
        first = await collect_tracked(factory, [recovered], run_ids)
        replay = await collect_tracked(factory, [
            recovered.model_copy(update={'observed_at': NOW + timedelta(minutes=10)})], run_ids)
        assert first.captures_written == 1 and replay.captures_written == 0
        async with factory() as session:
            fact = await session.scalar(select(TemporalFactRecord).where(
                TemporalFactRecord.fact_type == 'provider_game_evidence',
                TemporalFactRecord.fact_metadata['external_event_id'].astext == e.external_id))
            assert fact.value['plays'][3]['reported_home'] == 0
            assert fact.value['plays'][3]['home'] == 1
            assert fact.value['reported_pbp_errors']
            assert fact.observed_at == fact.available_at == NOW
            pipeline = MorningRankingPipeline(session)
            assert await pipeline.derive(fact.game_id, as_of=NOW - timedelta(seconds=1)) is None
            assert await pipeline.derive(fact.game_id, as_of=NOW + timedelta(hours=1)) is not None
    finally:
        await cleanup_test_runs(factory, run_ids)
        await engine.dispose()


@pytest.mark.parametrize("fault", ["observation_tie", "nonfinal", "future_valid_fact", "non_nba"])
async def test_batch_and_single_agree_on_latest_observation_and_validity(fault):
    from nba_time_machine.db import GameObservationRecord, GameRecord, SeasonRecord
    engine, factory = await setup()
    try:
        game, _ = await capture(factory)
        cutoff = NOW + timedelta(hours=1)
        async with factory.begin() as session:
            observation = await session.scalar(select(GameObservationRecord).where(GameObservationRecord.game_id == game))
            if fault == "observation_tie":
                # Same-provider/timestamp duplicates are forbidden by schema;
                # competing providers can still make the latest state ambiguous.
                session.add(GameObservationRecord(game_id=game, source_id=SOURCE_IDS["cbs"],
                    observed_at=observation.observed_at, available_at=observation.available_at,
                    status=observation.status, scheduled_tip_at=observation.scheduled_tip_at,
                    home_score=observation.home_score, away_score=observation.away_score))
            elif fault == "nonfinal":
                session.add(GameObservationRecord(game_id=game, source_id=observation.source_id,
                    observed_at=NOW + timedelta(minutes=1), available_at=NOW + timedelta(minutes=1),
                    status="in_progress", scheduled_tip_at=observation.scheduled_tip_at))
            elif fault == "future_valid_fact":
                fact = await session.scalar(select(TemporalFactRecord).where(
                    TemporalFactRecord.game_id == game, TemporalFactRecord.fact_type == "provider_game_evidence"))
                # Both readers exclude this row before selecting the newest
                # valid feature revision, preserving their existing contract.
                session.add(TemporalFactRecord(subject_type="game", game_id=game,
                    source_id=fact.source_id, fact_type=fact.fact_type, value={"broken": True},
                    observed_at=NOW + timedelta(minutes=1), available_at=NOW + timedelta(minutes=1),
                    valid_from=cutoff + timedelta(hours=1)))
            else:
                row = await session.get(GameRecord, game)
                season = await session.get(SeasonRecord, row.season_id)
                season.league = "OTHER"
        async with factory() as session:
            pipeline = MorningRankingPipeline(session)
            for at in (NOW - timedelta(seconds=1), cutoff):
                single = await pipeline.derive(game, as_of=at)
                batched = await pipeline.derive_many((game, uuid4()), as_of=at)
                assert batched[game] == single
                assert sum(result is not None for result in batched.values()) == int(
                    fault == "future_valid_fact" and at == cutoff)
    finally:
        await engine.dispose()
