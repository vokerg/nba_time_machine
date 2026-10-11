"""Git-reviewed desired-state source sync and runtime source health projections.

Only columns owned by SourceDefinition are reconciled. Collection state, historic
source outcomes, and runtime cursors are never read from or written by the seed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db.models import CollectionRunRecord, SourceOutcomeRecord, SourceRecord
from nba_time_machine.ingestion.contracts import SourceDefinition, VerificationStatus


class SourceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    status: Literal["seed_research_backlog"]
    notes: list[str] = Field(default_factory=list)
    sources: list[SourceDefinition]

    @model_validator(mode="after")
    def unique_source_ids(self) -> "SourceSeed":
        seen: set[str] = set()
        for source in self.sources:
            if source.id in seen:
                raise ValueError(f"duplicate source id: {source.id}")
            seen.add(source.id)
        return self


@dataclass(frozen=True)
class SyncResult:
    configured: int
    changed: int


@dataclass(frozen=True)
class SourceHealth:
    id: str
    name: str
    enabled: bool
    verification_status: str
    verified: bool
    last_status: str | None
    last_finished_at: datetime | None
    attempted: int
    succeeded: int
    failed: int
    skipped: int


# Deliberately excludes the database-owned runtime_cursor, created_at, and
# collection/outcome history. Omitting a source from a later seed does not delete it.
_DESIRED_FIELDS = (
    "name",
    "kind",
    "adapter",
    "category",
    "locator",
    "enabled",
    "verification_status",
    "cadence_minutes",
    "requires_auth",
    "retention_policy",
    "adapter_settings",
)
_SUCCESS = ("ok", "idle")
_SKIPPED = ("skipped_config",)


def load_source_seed(path: Path) -> SourceSeed:
    return SourceSeed.model_validate(json.loads(path.read_text(encoding="utf-8")))


async def sync_source_seed(session: AsyncSession, seed: SourceSeed) -> SyncResult:
    """Reconcile seed-owned columns transactionally; caller controls commit.

    INSERT .. ON CONFLICT is safe across concurrent sync invocations. The update
    WHERE clause skips unchanged records, including updated_at churn.
    """
    if not seed.sources:
        return SyncResult(configured=0, changed=0)

    insert_statement = pg_insert(SourceRecord).values(
        [source.model_dump(mode="json") for source in seed.sources]
    )
    changed_fields = {
        field: getattr(insert_statement.excluded, field) for field in _DESIRED_FIELDS
    }
    updates = {**changed_fields, "updated_at": func.now()}
    differing = or_(
        *(
            getattr(SourceRecord, field).is_distinct_from(
                getattr(insert_statement.excluded, field)
            )
            for field in _DESIRED_FIELDS
        )
    )
    statement = insert_statement.on_conflict_do_update(
        index_elements=[SourceRecord.id],
        set_=updates,
        where=differing,
    )
    result = await session.execute(statement)
    return SyncResult(configured=len(seed.sources), changed=result.rowcount)


async def list_source_health(session: AsyncSession) -> list[SourceHealth]:
    """Return all configured sources, including never-attempted/disabled sources.

    A partial, rate-limited, auth, blocked, parse or network result counts as a
    failed attempt; only skipped_config counts as skipped. No collector is run.
    """
    outcomes = (
        select(
            SourceOutcomeRecord.source_id.label("source_id"),
            func.count(SourceOutcomeRecord.id).label("attempted"),
            func.count(SourceOutcomeRecord.id)
            .filter(SourceOutcomeRecord.status.in_(_SUCCESS))
            .label("succeeded"),
            func.count(SourceOutcomeRecord.id)
            .filter(SourceOutcomeRecord.status.in_(_SKIPPED))
            .label("skipped"),
            func.count(SourceOutcomeRecord.id)
            .filter(~SourceOutcomeRecord.status.in_(_SUCCESS + _SKIPPED))
            .label("failed"),
        )
        .group_by(SourceOutcomeRecord.source_id)
        .subquery()
    )
    ranked = (
        select(
            SourceOutcomeRecord.source_id.label("source_id"),
            SourceOutcomeRecord.status.label("status"),
            SourceOutcomeRecord.finished_at.label("finished_at"),
            func.row_number()
            .over(
                partition_by=SourceOutcomeRecord.source_id,
                order_by=(CollectionRunRecord.started_at.desc(), SourceOutcomeRecord.id.desc()),
            )
            .label("position"),
        )
        .join(
            CollectionRunRecord,
            CollectionRunRecord.id == SourceOutcomeRecord.collection_run_id,
        )
        .subquery()
    )
    latest = (
        select(ranked.c.source_id, ranked.c.status, ranked.c.finished_at)
        .where(ranked.c.position == 1)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                SourceRecord,
                latest.c.status,
                latest.c.finished_at,
                outcomes.c.attempted,
                outcomes.c.succeeded,
                outcomes.c.failed,
                outcomes.c.skipped,
            )
            .outerjoin(latest, SourceRecord.id == latest.c.source_id)
            .outerjoin(outcomes, SourceRecord.id == outcomes.c.source_id)
            .order_by(SourceRecord.id)
        )
    ).all()
    return [
        SourceHealth(
            id=source.id,
            name=source.name,
            enabled=source.enabled,
            verification_status=source.verification_status,
            verified=source.verification_status == VerificationStatus.VERIFIED,
            last_status=last_status,
            last_finished_at=last_finished,
            attempted=int(attempted or 0),
            succeeded=int(succeeded or 0),
            failed=int(failed or 0),
            skipped=int(skipped or 0),
        )
        for source, last_status, last_finished, attempted, succeeded, failed, skipped in rows
    ]
