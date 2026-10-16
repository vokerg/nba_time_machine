"""Operator projections use canonical evidence and a PostgreSQL read-only transaction."""
from datetime import timedelta
import pytest
from sqlalchemy import select, text

from integration.test_morning_persistence import setup, evidence, FixtureCollector, DAY, NOW
from nba_time_machine.db import GameObservationRecord, TemporalFactRecord
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.operator.report import build_report

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_operator_reads_persisted_evidence_without_mutation():
    engine, factory = await setup()
    try:
        value = evidence()
        await MorningStore(factory, manual=True).collect(FixtureCollector([value]), DAY)
        async with factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                report = await build_report(session, day=DAY, source="espn-nba-games",
                                            now=NOW + timedelta(days=7))
                assert await session.scalar(text("SELECT current_setting('transaction_read_only')")) == "on"
        assert report["day"] == DAY.isoformat()
        assert any(s["id"] == "espn-nba-games" and not s["enabled"] for s in report["sources"])
        assert report["games"]
        # Observed final game evidence comes from a canonical fact. The source
        # filter cannot silently substitute another provider's player rows.
        assert any(g["status"] == "final"
                   and g["play_by_play"]["source"] == "espn-nba-games"
                   and g["play_by_play"]["status"] == "complete"
                   and g["player_box"]["status"] == "complete"
                   for g in report["games"])
        assert all(g["team_box"]["status"] == "unsupported" for g in report["games"])
        assert report["outcomes"] and all(o["source_id"] == "espn-nba-games"
                                          for o in report["outcomes"])
        assert not any("raw_payload" in str(game) for game in report["games"])
    finally:
        await engine.dispose()


async def test_rescheduled_game_is_removed_from_obsolete_eastern_day():
    engine, factory = await setup()
    try:
        value = evidence()
        await MorningStore(factory, manual=True).collect(FixtureCollector([value]), DAY)
        async with factory.begin() as session:
            game_id = await session.scalar(select(TemporalFactRecord.game_id).where(
                TemporalFactRecord.fact_metadata["external_event_id"].astext == value.external_id
            ).order_by(TemporalFactRecord.observed_at.desc()).limit(1))
            assert game_id is not None
            session.add(GameObservationRecord(
                game_id=game_id, source_id="espn-nba-games",
                observed_at=NOW + timedelta(days=1),
                available_at=NOW + timedelta(days=1),
                status="scheduled",
                scheduled_tip_at=value.ref.scheduled_at + timedelta(days=1),
                observation_metadata={"synthetic_reschedule": True},
            ))
        async with factory() as session:
            old = await build_report(session, day=DAY, source="espn-nba-games")
            new = await build_report(session, day=DAY + timedelta(days=1), source="espn-nba-games")
        assert all(g["game_id"] != str(game_id) for g in old["games"])
        assert any(g["game_id"] == str(game_id) and g["status"] == "scheduled"
                   for g in new["games"])
    finally:
        await engine.dispose()
