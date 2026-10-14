"""Synthetic evidence only, against explicitly configured disposable PostgreSQL."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from morning_fixtures import cbs_html, scoreboard, summary
from nba_time_machine.db import (
    DatabaseSettings, GameObservationRecord, GameRecord, RawCaptureRecord,
    SourceOutcomeRecord, SourceRecord, SportsExternalIdentityRecord, TeamRecord,
    TemporalFactRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.sports import cbs, espn
from nba_time_machine.sports.contracts import NormalizedGameObservation, NormalizedProviderTeam
from nba_time_machine.sports.errors import SportsProviderResponseError
from nba_time_machine.sports.morning import Attempt, GameResult, MorningReport, SOURCE_IDS
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.repository import StructuredSportsStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
DAY = date(2026, 10, 13)
NOW = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)


async def setup():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("disposable DATABASE_URL not configured")
    if make_url(settings.application_sqlalchemy_url()).host not in ("localhost", "127.0.0.1", "postgres"):
        pytest.skip("only disposable local/CI PostgreSQL permitted")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    async with factory.begin() as session:
        for provider, source_id in SOURCE_IDS.items():
            source = await session.get(SourceRecord, source_id)
            if source is None:
                source = SourceRecord(id=source_id, name=provider, kind="structured", adapter=provider + "_nba",
                    category=[], locator="https://site.api.espn.com" if provider == "espn" else "https://www.cbssports.com",
                    enabled=False, verification_status="verified", cadence_minutes=1440,
                    requires_auth=False, retention_policy="normalized_full", adapter_settings={})
                session.add(source)
    return engine, factory


def evidence():
    data = summary(event=str(uuid4().int)[:12])
    ref = espn.scoreboard(scoreboard(data), DAY)[0]
    return espn.summary(data, ref, NOW)


class FixtureCollector:
    def __init__(self, values, callback=None):
        self.values, self.callback = values, callback

    async def collect(self, day, game_id=None):
        if self.callback:
            await self.callback()
        return MorningReport(day, NOW, games=[GameResult(e.ref, [e]) for e in self.values],
            attempts=[Attempt(e.provider, "summary", e.external_id, "ok", 200) for e in self.values])


async def test_replay_corrections_and_cross_provider_match_append_existing_tables():
    engine, factory = await setup()
    e = evidence()
    store = MorningStore(factory, manual=True)
    try:
        first = await store.collect(FixtureCollector([e]), DAY)
        replay = await store.collect(FixtureCollector([e.model_copy(update={"observed_at": NOW + timedelta(hours=1)})]), DAY)
        corrected = e.model_copy(update={"notes": e.notes + ("synthetic_correction",), "observed_at": NOW + timedelta(hours=2)})
        correction = await store.collect(FixtureCollector([corrected]), DAY)
        assert first.captures_written == correction.captures_written == 1
        assert replay.captures_written == 0
        # A different provider's game identity joins the same dated matchup.
        backup = cbs.gametracker(cbs_html(), e.ref, NOW + timedelta(hours=3))
        backup = backup.model_copy(update={"external_id": str(uuid4().int)[:12]})
        second_provider = await store.collect(FixtureCollector([backup]), DAY)
        assert second_provider.captures_written == 1
        async with factory() as session:
            ids = list((await session.scalars(select(SportsExternalIdentityRecord).where(
                SportsExternalIdentityRecord.entity_type == "game",
                SportsExternalIdentityRecord.external_id.in_([e.external_id, backup.external_id]),
            ))).all())
            assert len(ids) == 2 and ids[0].game_id == ids[1].game_id
            captures = list((await session.scalars(select(RawCaptureRecord).where(
                RawCaptureRecord.external_id == "game:" + e.external_id))).all())
            assert len(captures) == 2 and all(c.raw_payload is None for c in captures)
            facts = list((await session.scalars(select(TemporalFactRecord).where(
                TemporalFactRecord.fact_metadata["external_event_id"].astext == e.external_id))).all())
            assert len(facts) == 2
            assert all(f.available_at == f.observed_at == f.valid_from for f in facts)
            assert facts[0].available_at >= NOW > e.ref.scheduled_at
            observations = list((await session.scalars(select(GameObservationRecord).where(
                GameObservationRecord.game_id == ids[0].game_id,
                GameObservationRecord.source_id == SOURCE_IDS["espn"],
                GameObservationRecord.observed_at.in_([NOW, NOW + timedelta(hours=2)]),
            ))).all())
            assert observations and all(o.final_at is None and o.actual_tip_at is None for o in observations)
            outcome = await session.scalar(select(SourceOutcomeRecord).where(
                SourceOutcomeRecord.collection_run_id == second_provider.run_id,
                SourceOutcomeRecord.source_id == SOURCE_IDS["cbs"]))
            assert outcome.status == "partial" and outcome.outcome_metadata["pbp_usable"] == 0
    finally:
        await engine.dispose()


async def test_retention_downgrade_in_flight_discards_capture_and_fact():
    engine, factory = await setup()
    e = evidence()
    async def revoke():
        async with factory.begin() as session:
            row = await session.get(SourceRecord, SOURCE_IDS["espn"])
            row.retention_policy = "metadata_only"
    try:
        r = await MorningStore(factory, manual=True).collect(FixtureCollector([e], revoke), DAY)
        assert r.captures_written == 0 and r.persistence_errors == ["espn:source_policy_changed"]
        async with factory() as session:
            assert not await session.scalar(select(RawCaptureRecord.id).where(RawCaptureRecord.external_id == "game:" + e.external_id))
    finally:
        async with factory.begin() as session:
            row = await session.get(SourceRecord, SOURCE_IDS["espn"])
            row.retention_policy = "normalized_full"
        await engine.dispose()


async def test_unverified_source_rejected_before_network_and_manual_does_not_enable_it():
    engine, factory = await setup()
    class NoNetwork:
        async def collect(self, *args, **kwargs):
            pytest.fail("network must not start")
    try:
        with pytest.raises(ValueError, match="not_ready"):
            await MorningStore(factory).collect(NoNetwork(), DAY)
        async with factory.begin() as session:
            row = await session.get(SourceRecord, SOURCE_IDS["espn"])
            row.verification_status = "unverified"
        with pytest.raises(ValueError, match="not_ready"):
            await MorningStore(factory, manual=True).collect(NoNetwork(), DAY)
    finally:
        async with factory.begin() as session:
            row = await session.get(SourceRecord, SOURCE_IDS["espn"])
            row.verification_status = "verified"
            assert row.enabled is False
        await engine.dispose()


async def test_ambiguous_team_identity_is_quarantined_without_creating_game():
    engine, factory = await setup()
    name = "Synthetic ambiguous " + str(uuid4())
    normalized = NormalizedGameObservation(external_event_id=str(uuid4()), season_label="2026-2027",
        home_team=NormalizedProviderTeam(str(uuid4()), name),
        away_team=NormalizedProviderTeam(str(uuid4()), "Synthetic away"), status="final",
        scheduled_tip_at=NOW, home_score=4, away_score=3)
    try:
        async with factory() as session:
            session.add_all([TeamRecord(league="NBA", name=name), TeamRecord(league="NBA", name=name)])
            await session.flush()
            with pytest.raises(SportsProviderResponseError, match="Ambiguous"):
                await StructuredSportsStore(source_id=SOURCE_IDS["espn"], provider_key="espn", reconcile_existing=True).resolve_game_identity(session, normalized)
            await session.rollback()
    finally:
        await engine.dispose()


async def test_ambiguous_same_day_matchups_are_not_silently_joined():
    engine, factory = await setup()
    key = str(uuid4())
    normalized = NormalizedGameObservation(external_event_id=key, season_label="2026-2027",
        home_team=NormalizedProviderTeam(key + "H", "Home " + key),
        away_team=NormalizedProviderTeam(key + "A", "Away " + key), status="final",
        scheduled_tip_at=NOW, home_score=4, away_score=3)
    store = StructuredSportsStore(source_id=SOURCE_IDS["espn"], provider_key="espn", reconcile_existing=True)
    try:
        async with factory() as session:
            season = await store._ensure_season(session, normalized.season_label)
            home = await store._ensure_team(session, normalized.home_team)
            away = await store._ensure_team(session, normalized.away_team)
            for _ in range(2):
                game = GameRecord(season_id=season.id, home_team_id=home.id, away_team_id=away.id)
                session.add(game)
                await session.flush()
                session.add(GameObservationRecord(game_id=game.id, source_id=SOURCE_IDS["espn"],
                    status="scheduled", scheduled_tip_at=NOW, observed_at=NOW, available_at=NOW))
            await session.flush()
            with pytest.raises(SportsProviderResponseError, match="Ambiguous canonical game"):
                await store.resolve_game_identity(session, normalized)
            await session.rollback()
    finally:
        await engine.dispose()
