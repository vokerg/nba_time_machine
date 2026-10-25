"""Local-only, explicit operator review of the latest captured media revision.

This is not a classifier and never verifies or enables a publisher. The reviewed
capture must be the current revision and must pass the same conservative
provenance contract as the general media read model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from nba_time_machine.db import (
    GameObservationRecord, MediaReviewRecord, RawCaptureRecord,
    SourceItemEntityLinkRecord, SourceItemRecord, SourceRecord,
)
from nba_time_machine.spoilers.media_feed import _trusted_capture


class ReviewRejected(ValueError):
    """Review was not applied; caller should not retry without reinspection."""


@dataclass(frozen=True)
class ReviewDecision:
    capture_id: UUID
    content_hash: str
    sensitivity: str
    game_ids: tuple[UUID, ...] = ()
    rights_cleared: bool = False
    link_cleared: bool = False


def _valid_decision(decision: ReviewDecision) -> None:
    if not decision.rights_cleared:
        raise ReviewRejected("source-specific rights clearance is required")
    if decision.sensitivity not in {"general", "pregame", "outcome_dependent"}:
        raise ReviewRejected("explicit spoiler classification is required")
    if len(decision.game_ids) != len(set(decision.game_ids)):
        raise ReviewRejected("duplicate game associations")
    if (decision.sensitivity == "general") != (not decision.game_ids):
        raise ReviewRejected("general must be unlinked; game-specific content needs games")
    if not decision.content_hash or len(decision.content_hash) != 64:
        raise ReviewRejected("exact 64-character capture hash is required")


def _latest_revision(item_id):
    latest_capture = aliased(RawCaptureRecord)
    return (
        select(latest_capture.id)
        .where(latest_capture.source_item_id == item_id)
        .order_by(latest_capture.captured_at.desc(), latest_capture.id.desc())
        .limit(1)
        .scalar_subquery()
    )


async def pending_reviews(session: AsyncSession, *, limit: int = 25, source_id: str | None = None) -> list[dict]:
    """Bounded operational metadata only; never emit unreviewed text in bulk."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    stmt = (
        select(SourceItemRecord.id, RawCaptureRecord.id, RawCaptureRecord.captured_at,
               RawCaptureRecord.content_hash, SourceRecord.id)
        .join(RawCaptureRecord, RawCaptureRecord.id == _latest_revision(SourceItemRecord.id))
        .join(SourceRecord, SourceRecord.id == SourceItemRecord.source_id)
        .outerjoin(MediaReviewRecord, MediaReviewRecord.capture_id == RawCaptureRecord.id)
        .where(MediaReviewRecord.capture_id.is_(None), SourceRecord.kind.in_(("web", "media", "podcast")))
        .order_by(RawCaptureRecord.captured_at.desc(), RawCaptureRecord.id.desc())
        .limit(limit)
    )
    if source_id:
        stmt = stmt.where(SourceRecord.id == source_id)
    rows = (await session.execute(stmt)).all()
    return [
        {"source_id": source, "item_id": str(item), "capture_id": str(capture),
         "captured_at": stamp.isoformat(), "content_hash": digest}
        for item, capture, stamp, digest, source in rows
    ]


async def inspect_review(session: AsyncSession, capture_id: UUID) -> dict:
    """Inspection prints content *only* for one explicitly selected local capture."""
    capture = await session.get(RawCaptureRecord, capture_id)
    if capture is None or capture.source_item_id is None:
        raise ReviewRejected("capture not found or not normalized")
    item = await session.get(SourceItemRecord, capture.source_item_id)
    if item is None:
        raise ReviewRejected("normalized item missing")
    source = await session.get(SourceRecord, item.source_id)
    if source is None:
        raise ReviewRejected("source missing")
    latest = await session.scalar(
        select(RawCaptureRecord.id).where(RawCaptureRecord.source_item_id == item.id)
        .order_by(RawCaptureRecord.captured_at.desc(), RawCaptureRecord.id.desc()).limit(1)
    )
    review = await session.get(MediaReviewRecord, capture_id)
    return {
        "source_id": source.id, "source_name": source.name,
        "verification_status": source.verification_status,
        "source_kind": source.kind, "retention_policy": source.retention_policy,
        "item_id": str(item.id), "capture_id": str(capture.id),
        "is_latest": latest == capture.id, "already_reviewed": review is not None,
        "content_hash": capture.content_hash,
        "published_at": capture.published_at.isoformat() if capture.published_at else None,
        "discovered_at": capture.discovered_at.isoformat(),
        "captured_at": capture.captured_at.isoformat(),
        "available_at": capture.available_at.isoformat() if capture.available_at else None,
        "title": capture.title, "excerpt": (capture.text_content or "")[:280] or None,
        "url": capture.canonical_url,
        "warning": "Unreviewed content may contain game results or other spoilers",
    }


async def approve_review(session: AsyncSession, decision: ReviewDecision, *, now: datetime | None = None) -> datetime:
    """Insert exactly one review, never change source authorization or past times.

    Caller owns the transaction. The item row lock serializes competing operator
    approvals; a later unreviewed capture automatically hides the older review.
    """
    _valid_decision(decision)
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ReviewRejected("review time must be timezone-aware")
    stamp = stamp.astimezone(timezone.utc)
    capture = await session.get(RawCaptureRecord, decision.capture_id)
    if capture is None or capture.source_item_id is None:
        raise ReviewRejected("capture not found or not normalized")
    item = await session.scalar(
        select(SourceItemRecord).where(SourceItemRecord.id == capture.source_item_id).with_for_update()
    )
    if item is None:
        raise ReviewRejected("normalized item missing")
    source = await session.get(SourceRecord, item.source_id)
    if source is None or await session.get(MediaReviewRecord, capture.id) is not None:
        raise ReviewRejected("source missing or capture already reviewed")
    current = await session.scalar(
        select(RawCaptureRecord.id).where(RawCaptureRecord.source_item_id == item.id)
        .order_by(RawCaptureRecord.captured_at.desc(), RawCaptureRecord.id.desc()).limit(1)
    )
    if current != capture.id:
        raise ReviewRejected("capture is not the latest revision; reinspect the item")
    if decision.content_hash != capture.content_hash:
        raise ReviewRejected("capture hash changed; reinspect the item")
    review = MediaReviewRecord(
        capture_id=capture.id, reviewed_at=stamp, sensitivity=decision.sensitivity,
        game_ids=list(decision.game_ids), rights_cleared=True, link_cleared=decision.link_cleared,
    )
    if _trusted_capture(item, source, capture, review, stamp) is None:
        raise ReviewRejected("source, retention, classification or provenance is not reviewable")

    # Candidate links can veto clearance but never authorize it. Missing manual
    # associations still require the operator's explicit complete-set assertion.
    known_links = (await session.scalars(
        select(SourceItemEntityLinkRecord.game_id).where(
            SourceItemEntityLinkRecord.source_item_id == item.id,
            SourceItemEntityLinkRecord.entity_type == "game",
            SourceItemEntityLinkRecord.link_state == "present",
            SourceItemEntityLinkRecord.observed_at <= stamp,
            SourceItemEntityLinkRecord.available_at <= stamp,
        )
    )).all()
    if any(game is None or game not in decision.game_ids for game in known_links):
        raise ReviewRejected("known candidate links contradict the proposed game set")

    for game in decision.game_ids:
        tip = await session.scalar(
            select(GameObservationRecord.scheduled_tip_at).where(
                GameObservationRecord.game_id == game,
                GameObservationRecord.observed_at <= stamp,
                GameObservationRecord.available_at <= stamp,
                GameObservationRecord.scheduled_tip_at.is_not(None),
            ).order_by(GameObservationRecord.observed_at.desc(), GameObservationRecord.id.desc()).limit(1)
        )
        if tip is None or tip.tzinfo is None:
            raise ReviewRejected("linked game has no timeline-known tip observation")
    session.add(review)
    await session.flush()
    return stamp
