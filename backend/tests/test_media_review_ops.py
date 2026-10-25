"""Operator media review is an explicit provenance/rights boundary (#91)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from nba_time_machine.db import (
    CollectionRunRecord, DatabaseSettings, MediaReviewRecord, RawCaptureRecord,
    SourceItemRecord, SourceRecord, create_database_engine, create_session_factory,
)
from nba_time_machine.ingestion.media_review_ops import (
    ReviewDecision, ReviewRejected, _valid_decision, approve_review,
    inspect_review, pending_reviews,
)


def decision(**overrides):
    fields = dict(capture_id=uuid4(), content_hash="a" * 64, sensitivity="general",
                  rights_cleared=True, link_cleared=False)
    fields.update(overrides)
    return ReviewDecision(**fields)


@pytest.mark.parametrize("change", [
    {"rights_cleared": False},
    {"sensitivity": "unknown"},
    {"sensitivity": "pregame"},
    {"sensitivity": "outcome_dependent"},
    {"sensitivity": "general", "game_ids": (uuid4(),)},
    {"sensitivity": "pregame", "game_ids": (uuid4(), uuid4(), uuid4()) , "content_hash": "short"},
    {"sensitivity": "pregame", "game_ids": (lambda x: (x,x))(uuid4())},
    {"content_hash": ""},
])
def test_explicit_decisions_cannot_implicitly_authorize_media(change):
    with pytest.raises(ReviewRejected):
        _valid_decision(decision(**change))


def test_game_linkage_can_be_explicit_and_complete():
    _valid_decision(decision(sensitivity="outcome_dependent", game_ids=(uuid4(),)))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_queue_only_clears_latest_verified_revision_with_real_postgres():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    stamp = datetime.now(timezone.utc)
    old = stamp - timedelta(minutes=20)
    recent = stamp - timedelta(minutes=10)
    source_id = f"review-ops-test-{uuid4()}"
    item_id, older_id, newest_id, run_id = (uuid4() for _ in range(4))
    try:
        async with factory() as session:
            session.add(SourceRecord(
                id=source_id, name="Synthetic approved publisher", kind="media",
                adapter="rss", category=[], locator="https://example.org/feed",
                enabled=False, verification_status="verified", cadence_minutes=60,
                requires_auth=False, retention_policy="metadata_only",
            ))
            session.add(CollectionRunRecord(id=run_id, started_at=old))
            await session.flush()
            session.add(SourceItemRecord(
                id=item_id, source_id=source_id, canonical_identity=f"test:{item_id}",
                discovered_at=old, available_at=old, captured_at=old,
            ))
            await session.flush()
            session.add_all([
                RawCaptureRecord(
                    id=cap_id, collection_run_id=run_id, source_id=source_id,
                    source_item_id=item_id, external_id=str(item_id),
                    discovered_at=moment, captured_at=moment, available_at=moment,
                    title=title, content_type="application/rss+xml",
                    content_hash=digest,
                )
                for cap_id, moment, title, digest in (
                    (older_id, old, "Older headline", "a" * 64),
                    (newest_id, recent, "Revised headline", "b" * 64),
                )
            ])
            await session.flush()
            pending = await pending_reviews(session, source_id=source_id)
            assert [r["capture_id"] for r in pending] == [str(newest_id)]
            assert "title" not in pending[0]
            assert (await inspect_review(session, older_id))["is_latest"] is False
            preview = await inspect_review(session, newest_id)
            assert preview["title"] == "Revised headline"
            assert preview["content_hash"] == "b" * 64
            with pytest.raises(ReviewRejected, match="latest revision"):
                await approve_review(session, decision(capture_id=older_id), now=stamp)
            with pytest.raises(ReviewRejected, match="hash changed"):
                await approve_review(session, decision(capture_id=newest_id), now=stamp)
            with pytest.raises(ReviewRejected, match="rights clearance"):
                await approve_review(session, decision(capture_id=newest_id, content_hash="b"*64,
                                                      rights_cleared=False), now=stamp)
            assert await session.get(MediaReviewRecord, newest_id) is None
            reviewed_at = await approve_review(
                session, decision(capture_id=newest_id, content_hash="b"*64), now=stamp
            )
            assert reviewed_at == stamp
            assert (await session.get(MediaReviewRecord, newest_id)).reviewed_at == stamp
            assert await pending_reviews(session, source_id=source_id) == []
            with pytest.raises(ReviewRejected, match="already reviewed"):
                await approve_review(
                    session, decision(capture_id=newest_id, content_hash="b"*64), now=stamp
                )
            # The test never commits; the synthetic source and captures roll back.
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_rights_and_temporal_gates_are_enforced_before_review():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=5)
    source_id = f"review-reject-test-{uuid4()}"
    item_id, cap_id, run_id = (uuid4() for _ in range(3))
    try:
        async with factory() as session:
            source = SourceRecord(
                id=source_id, name="Unverified synthetic feed", kind="media",
                adapter="rss", category=[], locator="https://example.org/rss",
                enabled=False, verification_status="unverified", cadence_minutes=60,
                requires_auth=False, retention_policy="metadata_excerpt",
            )
            session.add_all([source, CollectionRunRecord(id=run_id, started_at=past)])
            await session.flush()
            session.add(SourceItemRecord(
                id=item_id, source_id=source_id, canonical_identity=str(item_id),
                discovered_at=past, captured_at=past, available_at=past,
            ))
            await session.flush()
            session.add(RawCaptureRecord(
                id=cap_id, collection_run_id=run_id, source_id=source_id,
                source_item_id=item_id, external_id=str(cap_id), title="Fixture only",
                content_hash="f"*64, discovered_at=past,
                captured_at=past, available_at=past, content_type="application/rss+xml",
            ))
            await session.flush()
            request = decision(capture_id=cap_id, content_hash="f"*64)
            with pytest.raises(ReviewRejected, match="not reviewable"):
                await approve_review(session, request, now=now)
            source.verification_status = "verified"
            await session.flush()
            with pytest.raises(ReviewRejected, match="not reviewable"):
                await approve_review(session, request, now=past-timedelta(seconds=1))
            assert await session.scalar(select(MediaReviewRecord).where(
                MediaReviewRecord.capture_id == cap_id
            )) is None
            await session.rollback()
    finally:
        await engine.dispose()
