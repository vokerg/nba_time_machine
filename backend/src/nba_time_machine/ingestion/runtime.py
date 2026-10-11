"""Cadence-aware, isolated collection with retention-enforcing PostgreSQL writes.

Only the reviewed/verified/enabled subset can make network requests. Each
source commits independently so one parse/network failure cannot roll back
another source's successful captures.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nba_time_machine.db.models import (
    CollectionRunRecord,
    RawCaptureRecord,
    SourceItemRecord,
    SourceOutcomeRecord,
    SourceRecord,
)
from nba_time_machine.ingestion.adapters import CollectionFailure, collect_source
from nba_time_machine.ingestion.contracts import RawCapture, SourceDefinition


@dataclass(frozen=True)
class SourceRun:
    source_id: str
    status: str
    items_seen: int = 0
    captures_written: int = 0
    error_code: str | None = None


@dataclass(frozen=True)
class RunSummary:
    run_id: UUID
    outcomes: tuple[SourceRun, ...]


def _definition(row: SourceRecord) -> SourceDefinition:
    return SourceDefinition.model_validate({
        field: getattr(row, field)
        for field in SourceDefinition.model_fields
    })


def _is_due(row: SourceRecord, now: datetime) -> bool:
    cursor = row.runtime_cursor or {}
    try:
        last = datetime.fromisoformat(cursor.get("last_attempt_at", ""))
    except (TypeError, ValueError):
        return True
    if last.tzinfo is None:
        return True
    return now >= last + timedelta(minutes=row.cadence_minutes)


def _identity(capture: RawCapture) -> str | None:
    if capture.external_id:
        return "external:" + capture.external_id
    if capture.canonical_url:
        return "url:" + capture.canonical_url
    return None


def _retained(
    policy: str, capture: RawCapture
) -> tuple[str | None, str | None]:
    """Final enforcement boundary; adapter output is never trusted for storage."""
    if policy == "full":
        return capture.text, capture.raw_payload
    if policy == "normalized_full":
        return capture.text, None
    if policy == "metadata_excerpt":
        return capture.text[:280] if capture.text else None, None
    if policy == "metadata_only":
        return None, None
    raise ValueError("unrecognized retention policy")


async def _save_capture(
    session: AsyncSession,
    row: SourceRecord,
    run_id: UUID,
    capture: RawCapture,
) -> bool:
    if capture.source_id != row.id:
        raise ValueError("adapter source mismatch")
    identity = _identity(capture)
    if identity is None:
        raise ValueError("capture has no stable identity")
    text, raw = _retained(row.retention_policy, capture)
    # Discovery is conservative: never backdate a new item to an unverified
    # publisher-provided timestamp. Raw revisions have their own availability.
    item = {
        "id": uuid4(),
        "source_id": row.id,
        "canonical_identity": identity,
        "external_id": capture.external_id,
        "canonical_url": capture.canonical_url,
        "title": capture.title,
        "author": capture.author,
        "text_content": text,
        "published_at": capture.published_at,
        "discovered_at": capture.discovered_at,
        "captured_at": capture.captured_at,
        "available_at": capture.discovered_at,
        "item_metadata": {},
    }
    statement = (
        pg_insert(SourceItemRecord).values(**item)
        .on_conflict_do_nothing(constraint="uq_source_items_source_identity")
        .returning(SourceItemRecord.id)
    )
    item_id = (await session.execute(statement)).scalar_one_or_none()
    if item_id is None:
        item_id = await session.scalar(
            select(SourceItemRecord.id).where(
                SourceItemRecord.source_id == row.id,
                SourceItemRecord.canonical_identity == identity,
            )
        )
    if item_id is None:
        raise RuntimeError("could not resolve source item identity")

    previous_hash = await session.scalar(
        select(RawCaptureRecord.content_hash)
        .where(RawCaptureRecord.source_item_id == item_id)
        .order_by(RawCaptureRecord.captured_at.desc(), RawCaptureRecord.id.desc())
        .limit(1)
    )
    if previous_hash == capture.content_hash:
        return False

    # Revision history is append-only. An updated source item must not rewrite
    # what an as-of cursor could see at the first discovery timestamp.
    session.add(RawCaptureRecord(
        id=uuid4(),
        source_id=row.id,
        collection_run_id=run_id,
        source_item_id=item_id,
        external_id=capture.external_id,
        canonical_url=capture.canonical_url,
        published_at=capture.published_at,
        discovered_at=capture.discovered_at,
        captured_at=capture.captured_at,
        available_at=capture.discovered_at,
        content_type=capture.content_type,
        title=capture.title,
        author=capture.author,
        text_content=text,
        raw_payload=raw,
        content_hash=capture.content_hash,
        capture_metadata={},  # source-provided metadata is not a retention bypass
    ))
    return True


async def _save_outcome(
    session: AsyncSession,
    row: SourceRecord,
    run_id: UUID,
    result: SourceRun,
    now: datetime,
    *,
    update_cursor: bool,
) -> None:
    session.add(SourceOutcomeRecord(
        id=uuid4(),
        collection_run_id=run_id,
        source_id=row.id,
        status=result.status,
        items_seen=result.items_seen,
        captures_written=result.captures_written,
        error_code=result.error_code,
        finished_at=now,
        outcome_metadata={},
    ))
    if update_cursor:
        row.runtime_cursor = {
            **(row.runtime_cursor or {}),
            "last_attempt_at": now.isoformat(),
        }


async def _persist(
    factory: async_sessionmaker[AsyncSession],
    row: SourceRecord,
    run_id: UUID,
    now: datetime,
    captures: tuple[RawCapture, ...],
    status: str,
    error_code: str | None,
    *,
    update_cursor: bool,
) -> SourceRun:
    async with factory() as session:
        async with session.begin():
            locked = await session.scalar(
                select(SourceRecord).where(SourceRecord.id == row.id).with_for_update()
            )
            if locked is None:
                raise RuntimeError("source disappeared during collection")
            written = 0
            seen: set[str] = set()
            for capture in captures:
                identity = _identity(capture)
                if identity is None or identity in seen:
                    continue
                seen.add(identity)
                if await _save_capture(session, locked, run_id, capture):
                    written += 1
            # A successful fetch with only unchanged entries is an idle run.
            final_status = "idle" if status == "ok" and written == 0 else status
            result = SourceRun(row.id, final_status, len(captures), written, error_code)
            await _save_outcome(
                session, locked, run_id, result, now, update_cursor=update_cursor
            )
            return result


async def collect_once(
    factory: async_sessionmaker[AsyncSession],
    *,
    source_ids: Iterable[str] | None = None,
    force: bool = False,
    concurrency: int = 4,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> RunSummary:
    """Execute one bounded pass. Force bypasses cadence, never source validation."""
    if not 1 <= concurrency <= 16:
        raise ValueError("concurrency must be between 1 and 16")
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    async with factory() as session:
        statement = select(SourceRecord).order_by(SourceRecord.id)
        if source_ids is None:
            statement = statement.where(SourceRecord.enabled.is_(True))
        else:
            ids = tuple(source_ids)
            statement = statement.where(SourceRecord.id.in_(ids))
        sources = list((await session.scalars(statement)).all())

    run_id = uuid4()
    async with factory() as session:
        session.add(CollectionRunRecord(
            id=run_id, started_at=stamp,
            collector_version="rss-web-v1",
        ))
        await session.commit()

    limit = asyncio.Semaphore(concurrency)

    async def process(row: SourceRecord, http: httpx.AsyncClient) -> SourceRun | None:
        if row.enabled and not force and not _is_due(row, stamp):
            return None  # a not-due source is not an attempted source
        async with limit:
            if not row.enabled or row.verification_status != "verified":
                status, captures, code = "skipped_config", (), "not_verified_or_enabled"
                update_cursor = False
            else:
                try:
                    result = await collect_source(_definition(row), http, stamp)
                    status, captures, code = result.status, result.captures, None
                except CollectionFailure as exc:
                    status, captures, code = exc.status, (), exc.code
                except Exception:
                    # Do not log exception text: parser/network output is untrusted.
                    status, captures, code = "partial", (), "unexpected_collector_error"
                update_cursor = status != "skipped_config"
            try:
                return await _persist(
                    factory, row, run_id, stamp, captures, status, code,
                    update_cursor=update_cursor,
                )
            except Exception:
                # Other sources still persist. Surface the failure rather than
                # incorrectly claiming the source's outcome was saved.
                return SourceRun(row.id, "partial", error_code="persist_failed")

    try:
        if client is not None:
            outcomes = await asyncio.gather(*(process(s, client) for s in sources))
        else:
            async with httpx.AsyncClient() as http:
                outcomes = await asyncio.gather(*(process(s, http) for s in sources))
    finally:
        async with factory() as session:
            run = await session.get(CollectionRunRecord, run_id)
            if run is not None:
                run.finished_at = datetime.now(timezone.utc)
                await session.commit()

    return RunSummary(run_id, tuple(item for item in outcomes if item is not None))
