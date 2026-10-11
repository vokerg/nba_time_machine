"""Transactional source desired-state sync against migrated PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nba_time_machine.db import (
    CollectionRunRecord,
    DatabaseSettings,
    SourceOutcomeRecord,
    SourceRecord,
    create_database_engine,
    create_session_factory,
)
from nba_time_machine.ingestion.registry import SourceSeed, list_source_health, sync_source_seed


def _settings_or_skip() -> DatabaseSettings:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


def _source(source_id: str, **updates: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": source_id,
        "name": "Fixture source",
        "kind": "web",
        "adapter": "web",
        "category": ["news"],
        "locator": "https://example.org/",
        "enabled": False,
        "verification_status": "unverified",
        "cadence_minutes": 30,
        "requires_auth": False,
        "retention_policy": "metadata_excerpt",
        "adapter_settings": {},
    }
    data.update(updates)
    return data


def _seed(*rows: dict[str, object]) -> SourceSeed:
    return SourceSeed.model_validate(
        {"schema_version": 1, "status": "seed_research_backlog", "sources": list(rows)}
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_sync_preserves_runtime_state_and_reports_health() -> None:
    engine = create_database_engine(_settings_or_skip())
    session_factory = create_session_factory(engine)
    first_id = f"registry-first-{uuid4()}"
    second_id = f"registry-second-{uuid4()}"
    now = datetime.now(timezone.utc)
    try:
        initial = _seed(_source(first_id))
        async with session_factory.begin() as session:
            assert (await sync_source_seed(session, initial)).changed == 1
            assert (await sync_source_seed(session, initial)).changed == 0

        async with session_factory.begin() as session:
            source = await session.get(SourceRecord, first_id)
            assert source is not None
            source.runtime_cursor = {"since": "before-sync"}
            runs = [
                CollectionRunRecord(id=uuid4(), started_at=now + timedelta(minutes=i))
                for i in range(3)
            ]
            session.add_all(runs)
            await session.flush()
            for run, status in zip(
                runs, ("ok", "skipped_config", "network_error"), strict=True
            ):
                session.add(
                    SourceOutcomeRecord(
                        id=uuid4(),
                        collection_run_id=run.id,
                        source_id=first_id,
                        status=status,
                        finished_at=run.started_at + timedelta(seconds=1),
                    )
                )

        changed = _seed(
            _source(
                first_id,
                name="Renamed source",
                enabled=True,
                verification_status="verified",
                cadence_minutes=5,
                adapter_settings={"mode": "feed"},
            ),
            _source(second_id),
        )
        async with session_factory.begin() as session:
            assert (await sync_source_seed(session, changed)).changed == 2
            assert (await sync_source_seed(session, changed)).changed == 0

        async with session_factory() as session:
            first = await session.get(SourceRecord, first_id)
            assert first is not None
            assert first.runtime_cursor == {"since": "before-sync"}
            assert first.name == "Renamed source"
            assert first.adapter_settings == {"mode": "feed"}
            assert first.enabled is True
            assert first.verification_status == "verified"
            assert first.cadence_minutes == 5
            assert await session.scalar(
                select(func.count()).select_from(SourceRecord).where(
                    SourceRecord.id.in_((first_id, second_id))
                )
            ) == 2

            health = {
                item.id: item
                for item in await list_source_health(session)
                if item.id in (first_id, second_id)
            }
            assert health[first_id].verified is True
            assert health[first_id].enabled is True
            assert (
                health[first_id].attempted,
                health[first_id].succeeded,
                health[first_id].failed,
                health[first_id].skipped,
            ) == (3, 1, 1, 1)
            assert health[first_id].last_status == "network_error"
            assert health[second_id].last_status is None
            assert health[second_id].attempted == 0
            assert health[second_id].verified is False
            assert health[second_id].enabled is False

        disabled = _seed(_source(first_id, enabled=False, verification_status="verified"))
        async with session_factory.begin() as session:
            assert (await sync_source_seed(session, disabled)).changed == 1

        async with session_factory() as session:
            first = await session.get(SourceRecord, first_id)
            second = await session.get(SourceRecord, second_id)
            assert first is not None and first.enabled is False
            assert first.runtime_cursor == {"since": "before-sync"}
            # A missing desired-state source is not erased or implicitly disabled.
            assert second is not None
            assert await session.scalar(
                select(func.count()).select_from(SourceOutcomeRecord).where(
                    SourceOutcomeRecord.source_id == first_id
                )
            ) == 3
    finally:
        await engine.dispose()
