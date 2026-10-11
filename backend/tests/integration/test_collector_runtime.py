"""PostgreSQL regression for isolation, append-only captures and retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

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
from nba_time_machine.ingestion.runtime import collect_once

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def _settings() -> DatabaseSettings:
    result = DatabaseSettings(_env_file=None)
    if not result.is_configured:
        pytest.skip("DATABASE_URL not configured")
    return result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_isolated_collection_retention_revisions_and_cadence() -> None:
    engine = create_database_engine(_settings())
    factory = create_session_factory(engine)
    suffix = str(uuid4())
    meta = f"ingest-meta-{suffix}"
    excerpt = f"ingest-excerpt-{suffix}"
    full = f"ingest-full-{suffix}"
    broken = f"ingest-broken-{suffix}"
    disabled = f"ingest-unverified-{suffix}"
    sources = (meta, excerpt, full, broken, disabled)
    page_version = 1

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("broken"):
            return httpx.Response(403)
        if request.url.path.endswith("article"):
            body = f"<html><head><title>Article</title></head><body>Page version {page_version}</body></html>"
            return httpx.Response(200, text=body, headers={"content-type": "text/html"})
        body = (
            "<rss><channel><item><guid>one</guid><title>Preview</title>"
            "<pubDate>Thu, 08 Oct 2026 08:00:00 GMT</pubDate>"
            "<description>" + ("T" * 400) + "</description>"
            "</item></channel></rss>"
        )
        return httpx.Response(200, text=body, headers={"content-type": "application/rss+xml"})

    try:
        async with factory() as session:
            session.add_all([
                SourceRecord(
                    id=key, name=key, kind="media",
                    adapter="web" if key == full else "rss",
                    locator=(
                        "https://example.com/article" if key == full else
                        "https://example.com/broken" if key == broken else
                        "https://example.com/feed"
                    ),
                    enabled=True, verification_status=(
                        "unverified" if key == disabled else "verified"
                    ),
                    cadence_minutes=60, requires_auth=False,
                    retention_policy=(
                        "metadata_only" if key == meta else
                        "metadata_excerpt" if key == excerpt else "full"
                    ),
                ) for key in sources
            ])
            await session.commit()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await collect_once(
                factory, source_ids=sources, now=NOW, force=True,
                concurrency=2, client=client,
            )
            results = {r.source_id: r for r in first.outcomes}
            assert results[meta].status == "ok"
            assert results[excerpt].status == "ok"
            assert results[full].status == "ok"
            assert results[broken].status == "blocked"
            assert results[disabled].status == "skipped_config"
            assert results[broken].captures_written == 0
            assert all(results[key].captures_written == 1 for key in (meta, excerpt, full))

            second = await collect_once(
                factory, source_ids=sources, now=NOW + timedelta(minutes=2),
                force=True, client=client,
            )
            second_results = {r.source_id: r for r in second.outcomes}
            assert all(second_results[key].status == "idle" for key in (meta, excerpt, full))

            # Cadence skips due entries without manufacturing a new outcome.
            not_due = await collect_once(
                factory, source_ids=(meta, excerpt, full),
                now=NOW + timedelta(minutes=3), client=client,
            )
            assert not_due.outcomes == ()

            page_version = 2
            changed = await collect_once(
                factory, source_ids=(full,), force=True,
                now=NOW + timedelta(minutes=4), client=client,
            )
            assert changed.outcomes[0].captures_written == 1

        async with factory() as session:
            rows = (
                await session.scalars(
                    select(RawCaptureRecord)
                    .where(RawCaptureRecord.source_id.in_(sources))
                    .order_by(RawCaptureRecord.captured_at)
                )
            ).all()
            grouped = {key: [c for c in rows if c.source_id == key] for key in sources}
            assert len(grouped[meta]) == 1
            assert len(grouped[excerpt]) == 1
            assert len(grouped[full]) == 2
            assert not grouped[broken] and not grouped[disabled]
            assert grouped[meta][0].text_content is None
            assert grouped[meta][0].raw_payload is None
            assert len(grouped[excerpt][0].text_content or "") == 280
            assert grouped[excerpt][0].raw_payload is None
            assert "Page version 1" in (grouped[full][0].raw_payload or "")
            assert "Page version 2" in (grouped[full][1].raw_payload or "")
            assert grouped[full][0].content_hash != grouped[full][1].content_hash

            items = (
                await session.scalars(
                    select(SourceItemRecord).where(SourceItemRecord.source_id == full)
                )
            ).all()
            assert len(items) == 1
            assert items[0].available_at == NOW
            assert items[0].captured_at == NOW
            assert "version 1" in (items[0].text_content or "")
            assert (await session.scalar(
                select(func.count()).select_from(SourceOutcomeRecord)
                .where(SourceOutcomeRecord.source_id == full)
            )) == 3
            assert (await session.get(CollectionRunRecord, first.run_id)).finished_at is not None
            source_row = await session.get(SourceRecord, full)
            assert source_row.runtime_cursor["last_attempt_at"] == (
                NOW + timedelta(minutes=4)
            ).isoformat()
    finally:
        await engine.dispose()
