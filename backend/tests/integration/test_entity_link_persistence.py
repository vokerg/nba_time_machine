"""PostgreSQL enforcement for append-only source-item sports links (issue #2)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nba_time_machine.db import (
    DatabaseSettings, GameRecord, PlayerRecord, SeasonRecord, SourceItemEntityLinkRecord,
    SourceItemRecord, SourceRecord, TeamRecord, create_database_engine,
    create_session_factory,
)


def _settings_or_skip() -> DatabaseSettings:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_links_are_independently_versioned_and_can_be_retracted() -> None:
    engine = create_database_engine(_settings_or_skip())
    factory = create_session_factory(engine)
    source_id = f"entity-link-{uuid4()}"
    item_id, game_id, player_id, home_id, away_id, season_id = (uuid4() for _ in range(6))
    observed_at = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    try:
        async with factory() as session:
            session.add_all([
                SourceRecord(
                    id=source_id, name="Unreviewed link fixture", kind="rss",
                    adapter="rss", category=["test"], locator="https://example.test/feed",
                    enabled=False, verification_status="unverified",
                    cadence_minutes=60, requires_auth=False, retention_policy="metadata_only",
                ),
                SeasonRecord(id=season_id, league="NBA", label=f"link-test-{uuid4()}"),
                TeamRecord(id=home_id, league="NBA", name="Home"),
                TeamRecord(id=away_id, league="NBA", name="Away"),
                PlayerRecord(id=player_id, full_name="Fixture Player"),
            ])
            await session.flush()
            session.add(GameRecord(
                id=game_id, season_id=season_id,
                home_team_id=home_id, away_team_id=away_id,
            ))
            session.add(SourceItemRecord(
                id=item_id, source_id=source_id, canonical_identity="episode:1",
                discovered_at=observed_at, captured_at=observed_at,
                available_at=observed_at,
            ))
            await session.commit()

        async with factory() as session:
            session.add_all([
                SourceItemEntityLinkRecord(
                    source_item_id=item_id, entity_type="game", game_id=game_id,
                    link_state="present", derivation_method="rule",
                    observed_at=observed_at, available_at=observed_at,
                ),
                SourceItemEntityLinkRecord(
                    source_item_id=item_id, entity_type="player", player_id=player_id,
                    link_state="present", derivation_method="model",
                    observed_at=observed_at, available_at=observed_at,
                ),
                SourceItemEntityLinkRecord(
                    source_item_id=item_id, entity_type="team", team_id=home_id,
                    link_state="present", derivation_method="manual",
                    observed_at=observed_at, available_at=observed_at,
                ),
            ])
            await session.commit()

        async with factory() as session:
            session.add(SourceItemEntityLinkRecord(
                source_item_id=item_id, entity_type="game", game_id=game_id,
                link_state="retracted", derivation_method="manual",
                observed_at=observed_at + timedelta(minutes=1),
                available_at=observed_at + timedelta(minutes=1),
            ))
            await session.commit()

        async with factory() as session:
            rows = (await session.scalars(
                select(SourceItemEntityLinkRecord)
                .where(SourceItemEntityLinkRecord.source_item_id == item_id)
                .order_by(SourceItemEntityLinkRecord.observed_at, SourceItemEntityLinkRecord.entity_type)
            )).all()
        assert len(rows) == 4
        assert [row.link_state for row in rows if row.game_id == game_id] == [
            "present", "retracted",
        ]
        assert {row.entity_type for row in rows} == {"game", "team", "player"}
        assert all(row.available_at.tzinfo is not None for row in rows)

        invalid = [
            dict(entity_type="game", game_id=game_id, link_state="present",
                 derivation_method="rule"),
            dict(entity_type="game", link_state="present",
                 derivation_method="rule"),
            dict(entity_type="game", team_id=home_id, link_state="present",
                 derivation_method="rule"),
            dict(entity_type="game", game_id=game_id, team_id=home_id,
                 link_state="present", derivation_method="rule"),
            dict(entity_type="team", team_id=home_id, link_state="unknown",
                 derivation_method="rule"),
            dict(entity_type="player", player_id=player_id, link_state="present",
                 derivation_method="untrusted"),
            dict(entity_type="player", player_id=uuid4(), link_state="present",
                 derivation_method="model"),
        ]
        for index, values in enumerate(invalid):
            # Only the first case deliberately collides with an existing
            # observation. Fresh clocks ensure later failures test their
            # intended check/FK, not the uniqueness index.
            timestamp = observed_at if index == 0 else (
                observed_at + timedelta(minutes=10 + index)
            )
            async with factory() as session:
                session.add(SourceItemEntityLinkRecord(
                    source_item_id=item_id,
                    observed_at=timestamp, available_at=timestamp,
                    **values,
                ))
                with pytest.raises(IntegrityError):
                    await session.commit()

        async with factory() as session:
            session.add(SourceItemEntityLinkRecord(
                source_item_id=item_id, entity_type="team", team_id=away_id,
                link_state="present", derivation_method="manual",
                observed_at=observed_at + timedelta(minutes=2),
                available_at=observed_at + timedelta(minutes=1),
            ))
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
