from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nba_time_machine.db import (
    CollectionRunRecord,
    DatabaseSettings,
    RawCaptureRecord,
    SourceItemRecord,
    SourceOutcomeRecord,
    SourceRecord,
    create_database_engine,
    create_session_factory,
)


def _database_settings_or_skip() -> DatabaseSettings:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    return settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_capture_history_preserves_temporal_provenance_across_runs() -> None:
    engine = create_database_engine(_database_settings_or_skip())
    session_factory = create_session_factory(engine)

    source_id = f"test-source-{uuid4()}"
    item_id = uuid4()
    run_one_id = uuid4()
    run_two_id = uuid4()

    published_at = datetime.now(timezone.utc) - timedelta(hours=2)
    discovered_at = published_at + timedelta(minutes=20)
    available_at = discovered_at
    first_capture_at = discovered_at + timedelta(minutes=5)
    second_capture_at = first_capture_at + timedelta(hours=1)

    try:
        async with session_factory() as session:
            session.add_all(
                [
                    SourceRecord(
                        id=source_id,
                        name="Schema test source",
                        kind="web",
                        adapter="web",
                        category=["test"],
                        locator="https://example.test/source",
                        enabled=False,
                        verification_status="unverified",
                        cadence_minutes=15,
                        requires_auth=False,
                        retention_policy="metadata_excerpt",
                    ),
                    CollectionRunRecord(
                        id=run_one_id,
                        started_at=first_capture_at - timedelta(minutes=1),
                    ),
                ]
            )
            await session.flush()

            session.add(
                SourceItemRecord(
                    id=item_id,
                    source_id=source_id,
                    canonical_identity="article:42",
                    external_id="42",
                    canonical_url="https://example.test/articles/42",
                    title="Pregame context",
                    author="Example",
                    text_content="Normalized content",
                    published_at=published_at,
                    discovered_at=discovered_at,
                    captured_at=first_capture_at,
                    available_at=available_at,
                )
            )
            await session.flush()

            session.add_all(
                [
                    RawCaptureRecord(
                        id=uuid4(),
                        source_id=source_id,
                        collection_run_id=run_one_id,
                        source_item_id=item_id,
                        external_id="42",
                        canonical_url="https://example.test/articles/42",
                        published_at=published_at,
                        discovered_at=discovered_at,
                        captured_at=first_capture_at,
                        available_at=available_at,
                        content_type="text/html",
                        title="Pregame context",
                        author="Example",
                        text_content="Normalized content",
                        raw_payload="<html>capture one</html>",
                        content_hash="same-payload-hash",
                    ),
                    SourceOutcomeRecord(
                        id=uuid4(),
                        collection_run_id=run_one_id,
                        source_id=source_id,
                        status="ok",
                        items_seen=1,
                        captures_written=1,
                        finished_at=first_capture_at,
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            session.add(
                CollectionRunRecord(
                    id=run_two_id,
                    started_at=second_capture_at - timedelta(minutes=1),
                )
            )
            await session.flush()
            session.add(
                RawCaptureRecord(
                    id=uuid4(),
                    source_id=source_id,
                    collection_run_id=run_two_id,
                    source_item_id=item_id,
                    external_id="42",
                    canonical_url="https://example.test/articles/42",
                    published_at=published_at,
                    discovered_at=discovered_at,
                    captured_at=second_capture_at,
                    available_at=available_at,
                    content_type="text/html",
                    title="Pregame context",
                    author="Example",
                    text_content="Normalized content",
                    raw_payload="<html>capture one</html>",
                    content_hash="same-payload-hash",
                )
            )
            await session.commit()

        async with session_factory() as session:
            captures = (
                await session.scalars(
                    select(RawCaptureRecord)
                    .where(RawCaptureRecord.source_item_id == item_id)
                    .order_by(RawCaptureRecord.captured_at)
                )
            ).all()
            item = await session.get(SourceItemRecord, item_id)

        assert item is not None
        assert item.published_at == published_at
        assert item.discovered_at == discovered_at
        assert item.captured_at == first_capture_at
        assert item.available_at == available_at
        assert len(captures) == 2
        assert captures[0].collection_run_id == run_one_id
        assert captures[1].collection_run_id == run_two_id
        assert captures[0].content_hash == captures[1].content_hash
        assert captures[0].captured_at < captures[1].captured_at
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_enforces_logical_identity_and_per_run_idempotency() -> None:
    engine = create_database_engine(_database_settings_or_skip())
    session_factory = create_session_factory(engine)

    source_id = f"test-source-{uuid4()}"
    run_id = uuid4()
    item_id = uuid4()
    now = datetime.now(timezone.utc)

    try:
        async with session_factory() as session:
            session.add_all(
                [
                    SourceRecord(
                        id=source_id,
                        name="Constraint test source",
                        kind="media",
                        adapter="rss_or_web",
                        category=["test"],
                        locator="https://example.test/feed",
                        enabled=False,
                        verification_status="unverified",
                        cadence_minutes=10,
                        requires_auth=False,
                        retention_policy="metadata_excerpt",
                    ),
                    CollectionRunRecord(id=run_id, started_at=now),
                ]
            )
            await session.flush()

            session.add(
                SourceItemRecord(
                    id=item_id,
                    source_id=source_id,
                    canonical_identity="post:99",
                    external_id="99",
                    discovered_at=now,
                    captured_at=now,
                    available_at=now,
                )
            )
            await session.flush()

            session.add(
                RawCaptureRecord(
                    id=uuid4(),
                    source_id=source_id,
                    collection_run_id=run_id,
                    source_item_id=item_id,
                    external_id="99",
                    discovered_at=now,
                    captured_at=now,
                    available_at=now,
                    content_hash="hash-99",
                )
            )
            await session.commit()

        async with session_factory() as session:
            session.add(
                SourceItemRecord(
                    id=uuid4(),
                    source_id=source_id,
                    canonical_identity="post:99",
                    external_id="99-copy",
                    discovered_at=now,
                    captured_at=now,
                    available_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()

        async with session_factory() as session:
            session.add(
                RawCaptureRecord(
                    id=uuid4(),
                    source_id=source_id,
                    collection_run_id=run_id,
                    source_item_id=item_id,
                    external_id="99",
                    discovered_at=now,
                    captured_at=now + timedelta(seconds=1),
                    available_at=now,
                    content_hash="hash-99",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()

        async with session_factory() as session:
            session.add(
                SourceOutcomeRecord(
                    id=uuid4(),
                    collection_run_id=run_id,
                    source_id=source_id,
                    status="not-a-real-status",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
