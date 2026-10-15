"""Fail-closed reviewed-media read path; never infer spoiler safety from RSS dates.

The most recent captured revision as of the profile cursor must have its own
explicit review. A later unreviewed edit hides the item, not the old headline.
Only policy projections are serialized. Keyset ordering uses review timestamps
and immutable canonical UUIDs, not headline text or future popularity.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from nba_time_machine.api.read_models import (
    MediaFeedItemResponse, MediaFeedResponse, media_item_from_projection,
)
from nba_time_machine.db import (
    GameObservationRecord, RawCaptureRecord, SourceItemEntityLinkRecord, SourceItemRecord, SourceRecord,
)
from nba_time_machine.db.media_models import MediaReviewRecord
from nba_time_machine.ingestion.adapters import canonical_url
from nba_time_machine.spoilers.game_reader import SqlAlchemyGameSnapshotRepository, utc
from nba_time_machine.spoilers.policy import (
    GameContext, MediaField, MediaFieldName, MediaItem, MediaSensitivity,
    project_general_media,
)
from nba_time_machine.spoilers.repository import SqlAlchemyGameAcknowledgementRepository


@dataclass(frozen=True)
class PageKey:
    reviewed_at: datetime
    item_id: UUID


def encode_page(key: PageKey, cursor: datetime) -> str:
    payload = [utc(cursor).isoformat(), utc(key.reviewed_at).isoformat(), str(key.item_id)]
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_page(token: str | None, cursor: datetime) -> PageKey | None:
    if token is None:
        return None
    if len(token) > 512:
        raise ValueError("invalid page token")
    try:
        data = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True))
        if not isinstance(data, list) or len(data) != 3 or not all(isinstance(v, str) for v in data):
            raise ValueError("invalid page token")
        if datetime.fromisoformat(data[0]) != utc(cursor):
            raise ValueError("page token belongs to another timeline")
        stamp = utc(datetime.fromisoformat(data[1]))
        identifier = UUID(data[2])
        if stamp is None or stamp > cursor:
            raise ValueError("invalid page token timestamp")
        return PageKey(stamp, identifier)
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid or stale page token") from exc


def _trusted_capture(
    item: SourceItemRecord, source: SourceRecord, capture: RawCaptureRecord,
    review: MediaReviewRecord, cursor: datetime,
) -> tuple[MediaItem, datetime] | None:
    """Require actual observations and revision-specific operator clearance."""
    times = [
        utc(item.discovered_at), utc(item.available_at),
        utc(capture.discovered_at), utc(capture.captured_at),
        utc(capture.available_at), utc(review.reviewed_at),
    ]
    if (
        not review.rights_cleared or any(value is None or value > cursor for value in times)
        or times[3] < times[2] or times[4] < times[2]
        or times[5] < times[3]
        or item.source_id != source.id or capture.source_id != source.id
        or capture.source_item_id != item.id
        or source.verification_status != "verified" or source.requires_auth
        or source.kind not in ("web", "podcast", "video")
        or source.retention_policy not in ("full", "normalized_full", "metadata_excerpt", "metadata_only")
        or capture.content_type not in ("application/rss+xml", "application/atom+xml", "text/html")
        or not isinstance(capture.title, str) or not capture.title.strip()
        or review.game_ids is None or len(review.game_ids) != len(set(review.game_ids))
    ):
        return None
    try:
        sensitivity = MediaSensitivity(review.sensitivity)
    except ValueError:
        return None
    if sensitivity is MediaSensitivity.UNKNOWN or (
        (sensitivity is MediaSensitivity.GENERAL) != (not review.game_ids)
    ):
        return None
    # Reviewed_at is deliberately not backdated to an unverified pubDate.
    known = max(times)
    fields = [MediaField(MediaFieldName.HEADLINE, capture.title.strip(), known, known)]
    if source.retention_policy in ("full", "normalized_full", "metadata_excerpt") and capture.text_content:
        excerpt = capture.text_content.strip()[:280]
        if excerpt:
            fields.append(MediaField(MediaFieldName.EXCERPT, excerpt, known, known))
    return MediaItem(str(item.id), known, known, sensitivity, frozenset(review.game_ids), tuple(fields)), known


class MediaFeedService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.game_reader = SqlAlchemyGameSnapshotRepository(session)
        self.acks = SqlAlchemyGameAcknowledgementRepository(session)

    async def list_items(
        self, profile_id: UUID, *, cursor: datetime, limit: int, page: str | None = None,
    ) -> MediaFeedResponse:
        key = decode_page(page, cursor)
        selected: list[tuple[MediaFeedItemResponse, PageKey]] = []
        # Latest capture is selected before joining review. An unreviewed latest
        # revision therefore cannot fall back to a previously cleared headline.
        revision = aliased(RawCaptureRecord)
        latest = (
            select(revision.id)
            .where(revision.source_item_id == SourceItemRecord.id, revision.captured_at <= cursor)
            .order_by(revision.captured_at.desc(), revision.id.desc())
            .limit(1).correlate(SourceItemRecord).scalar_subquery()
        )
        while len(selected) <= limit:
            statement = (
                select(SourceItemRecord, SourceRecord, RawCaptureRecord, MediaReviewRecord)
                .join(SourceRecord, SourceRecord.id == SourceItemRecord.source_id)
                .join(RawCaptureRecord, RawCaptureRecord.id == latest)
                .join(MediaReviewRecord, MediaReviewRecord.capture_id == RawCaptureRecord.id)
                .where(
                    MediaReviewRecord.reviewed_at <= cursor,
                    SourceRecord.verification_status == "verified",
                    MediaReviewRecord.rights_cleared.is_(True),
                )
                .order_by(MediaReviewRecord.reviewed_at.desc(), SourceItemRecord.id.desc())
                .limit(64)
            )
            if key is not None:
                statement = statement.where(or_(
                    MediaReviewRecord.reviewed_at < key.reviewed_at,
                    and_(MediaReviewRecord.reviewed_at == key.reviewed_at, SourceItemRecord.id < key.item_id),
                ))
            rows = (await self.session.execute(statement)).all()
            if not rows:
                break
            for item, source, capture, review in rows:
                key = PageKey(review.reviewed_at, item.id)
                trusted = _trusted_capture(item, source, capture, review, cursor)
                if trusted is None:
                    continue
                media, known = trusted
                # Candidate links are untrusted. They can veto an incomplete
                # reviewer association but can never themselves grant exposure.
                linked = set((await self.session.scalars(
                    select(SourceItemEntityLinkRecord.game_id).where(
                        SourceItemEntityLinkRecord.source_item_id == item.id,
                        SourceItemEntityLinkRecord.entity_type == "game",
                        SourceItemEntityLinkRecord.link_state == "present",
                        SourceItemEntityLinkRecord.observed_at <= cursor,
                        SourceItemEntityLinkRecord.available_at <= cursor,
                    )
                )).all())
                if any(value is None or value not in media.related_game_ids for value in linked):
                    continue
                contexts: dict[UUID, GameContext] = {}
                for game_id in media.related_game_ids:
                    # Future-only schedule observations cannot make a pregame
                    # story eligible at a historical cursor.
                    known_tip = await self.session.scalar(
                        select(GameObservationRecord.scheduled_tip_at)
                        .where(
                            GameObservationRecord.game_id == game_id,
                            GameObservationRecord.observed_at <= cursor,
                            GameObservationRecord.available_at <= cursor,
                            GameObservationRecord.scheduled_tip_at.is_not(None),
                        )
                        .order_by(GameObservationRecord.observed_at.desc(), GameObservationRecord.id.desc())
                        .limit(1)
                    )
                    if utc(known_tip) is None:
                        break
                    snapshot = await self.game_reader.get(game_id, time_cursor=cursor)
                    if snapshot is None:
                        break
                    contexts[game_id] = GameContext(
                        game_id=game_id, time_cursor=cursor,
                        tip_at=utc(known_tip),
                        protection_ends_at=snapshot.protection_ends_at,
                        acknowledged=await self.acks.is_acknowledged(profile_id, game_id),
                    )
                if len(contexts) != len(media.related_game_ids):
                    continue
                projection = project_general_media((media,), time_cursor=cursor, games=contexts)
                if not projection:
                    continue
                safe = media_item_from_projection(projection[0])
                url = canonical_url(capture.canonical_url) if review.link_cleared else None
                if url is not None and not url.startswith("https://"):
                    url = None
                result = MediaFeedItemResponse(
                    **safe.model_dump(),
                    source=source.name, source_id=source.id,
                    media_type="podcast" if source.kind == "podcast" else ("video" if source.kind == "video" else "article"),
                    known_at=known, url=url,
                )
                selected.append((result, key))
                if len(selected) > limit:
                    break
            if len(selected) > limit or len(rows) < 64:
                break
        has_more = len(selected) > limit
        visible = selected[:limit]
        return MediaFeedResponse(
            time_cursor=cursor,
            items=tuple(item for item, _ in visible),
            next_page=encode_page(visible[-1][1], cursor) if has_more and visible else None,
        )
