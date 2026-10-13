"""Bounded sports collection; captured data is never a spoiler-safe projection."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, text

from nba_time_machine.db import (
    CollectionRunRecord, SourceOutcomeRecord, SourceRecord,
    TemporalFactRecord,
)
from nba_time_machine.ingestion.contracts import RawCapture
from nba_time_machine.ingestion.runtime import _save_capture
from nba_time_machine.sports.errors import SportsProviderError, SportsProviderResponseError
from nba_time_machine.sports.normalize import normalize_thesportsdb_event
from nba_time_machine.sports.repository import StructuredSportsStore

SOURCE = "thesportsdb-nba"
SEASONS = ("2025-2026", "2026-2027")


@dataclass
class CoverageReport:
    season: str
    run_id: str = ""
    requests: int = 0
    events_seen: int = 0
    games_stored: int = 0
    observations_written: int = 0
    captures_written: int = 0
    stats_written: int = 0
    stats_empty: int = 0
    rejected: int = 0
    failed_requests: int = 0
    limit_hits: list[str] = field(default_factory=list)
    last_completed_date: str | None = None
    complete_season_verified: bool = False
    gaps: list[str] = field(default_factory=lambda: [
        "No independent authoritative season manifest; completeness is unverified.",
        "No trustworthy historical publication, actual-tip or final timestamps.",
        "NBA standings, historical rosters and player box-score coverage unverified.",
        "V1 polling has no live-update SLA; premium v2 required for live scores.",
    ])


def validate_window(season: str, start: date | None, end: date | None) -> None:
    if season not in SEASONS:
        raise ValueError("only 2025-2026 and 2026-2027 are supported")
    if (start is None) != (end is None):
        raise ValueError("start and end must be supplied together")
    year = int(season[:4])
    if start is not None and not (
        date(year, 7, 1) <= start <= end < date(year + 1, 7, 1)
    ):
        raise ValueError("date window must be ordered and within the selected season")


def source_policy(source, manual: bool) -> tuple:
    if source is None or source.verification_status != "verified" or source.adapter != "thesportsdb":
        raise ValueError("verified TheSportsDB registry source required")
    if not source.enabled and not manual:
        raise ValueError("source disabled; explicit --manual required for operator collection")
    if source.requires_auth or source.retention_policy not in ("full", "normalized_full"):
        raise ValueError("reviewed structured-data retention/access required")
    return (source.enabled, source.verification_status, source.adapter, source.locator,
            source.requires_auth, source.retention_policy, source.adapter_settings)


class SportsCollector:
    def __init__(self, factory, client, *, max_requests=400, interval=2.1, manual=False):
        if not 1 <= max_requests <= 10000 or interval < 2.1:
            raise ValueError("bounded request budget and >=2.1 second pacing required")
        self.factory, self.client = factory, client
        self.max_requests, self.interval, self.manual = max_requests, interval, manual
        self.last_request = None
        self.store = StructuredSportsStore()

    async def collect(self, season, *, start=None, end=None, statistics=False):
        validate_window(season, start, end)
        report = CoverageReport(season)
        # Transaction-scoped lock survives short per-capture commits on other sessions. Overlapping jobs
        # fail before network requests; all sports writes use this one entry point.
        async with self.factory() as lock_session:
            locked = await lock_session.scalar(text("SELECT pg_try_advisory_xact_lock(734387)"))
            if not locked:
                raise ValueError("sports collection already running")
            try:
                return await self._run(report, start, end, statistics, lock_session)
            except Exception:
                if report.run_id:
                    report.gaps.append("Run interrupted by configuration/persistence failure; replay requested window.")
                    await self._checkpoint(report, finished=True)
                raise
            # Closing this session rolls back the dedicated lock transaction.
            # No session lock escapes onto a pooled connection, and no explicit
            # unlock can turn successfully persisted data into a failed CLI run.

    async def _run(self, report, start, end, statistics, lock_session):
        run_id = uuid4()
        report.run_id = str(run_id)
        async with self.factory.begin() as session:
            source = await session.get(SourceRecord, SOURCE)
            policy = source_policy(source, self.manual)
            session.add(CollectionRunRecord(id=run_id, started_at=datetime.now(timezone.utc),
                                           collector_version="sports-v1", run_metadata={"season": report.season}))
            await session.flush()
            session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=SOURCE,
                        status="partial", items_seen=0, captures_written=0,
                        outcome_metadata={"state": "running", "season": report.season}))
        seen = set()

        async def request(method, args, label, limit):
            if report.requests >= self.max_requests:
                if "Request budget exhausted; rerun remaining window." not in report.gaps:
                    report.gaps.append("Request budget exhausted; rerun remaining window.")
                return None
            if self.last_request is not None:
                await asyncio.sleep(max(0, self.interval - (monotonic() - self.last_request)))
            # Keep the dedicated transaction active and fail before requesting
            # more data if its lock connection is lost (Neon/pool idle timeout).
            await lock_session.execute(text("SELECT 1"))
            self.last_request = monotonic()
            report.requests += 1
            try:
                rows = await method(*args)
            except SportsProviderError:
                report.failed_requests += 1
                return None
            if len(rows) >= limit:
                report.limit_hits.append(label)
            return rows

        async def consume(events):
            for event in events:
                report.events_seen += 1
                try:
                    normalized = normalize_thesportsdb_event(event)
                    if normalized.season_label != report.season:
                        report.rejected += 1
                        continue
                    if normalized.external_event_id in seen:
                        continue
                    seen.add(normalized.external_event_id)
                    observed = datetime.now(timezone.utc)
                    async with self.factory.begin() as session:
                        source = await session.scalar(select(SourceRecord).where(SourceRecord.id == SOURCE).with_for_update())
                        if source_policy(source, self.manual) != policy:
                            raise ValueError("source policy changed during fetch")
                        payload = asdict(normalized)
                        body = json.dumps(payload, default=str, sort_keys=True)
                        capture = RawCapture(source_id=SOURCE, external_id="event:" + normalized.external_event_id,
                                             discovered_at=observed, captured_at=observed,
                                             content_type="application/json", text=body,
                                             raw_payload=json.dumps(event, sort_keys=True) if source.retention_policy == "full" else None,
                                             content_hash=hashlib.sha256(body.encode()).hexdigest())
                        changed = await _save_capture(session, source, run_id, capture)
                        # Repeated identical captures don't append observations or
                        # move first availability. Changed states append revisions.
                        if changed:
                            observation = await self.store.store_game_observation(session, normalized, observed_at=observed)
                            game_id = observation.game_id
                        else:
                            from nba_time_machine.db import SportsExternalIdentityRecord
                            game_id = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                                SportsExternalIdentityRecord.provider_key == "thesportsdb",
                                SportsExternalIdentityRecord.entity_type == "game",
                                SportsExternalIdentityRecord.external_id == normalized.external_event_id))
                            if game_id is None:
                                observation = await self.store.store_game_observation(session, normalized, observed_at=observed)
                                game_id = observation.game_id
                                changed = True
                    report.games_stored += 1
                    report.observations_written += int(changed)
                    report.captures_written += int(changed)
                    if statistics:
                        rows = await request(self.client.event_stats, (normalized.external_event_id,),
                                             "event_stats:" + normalized.external_event_id, 5)
                        if rows is None:
                            continue
                        if not rows:
                            report.stats_empty += 1
                            continue
                        await self._stats(rows, game_id, normalized.external_event_id, run_id, policy, report)
                except (SportsProviderResponseError, TypeError, OverflowError):
                    report.rejected += 1

        # v1 endpoints have no pagination. Always expose limit risk rather than
        # interpreting a full response as an exhaustive season.
        rows = await request(self.client.season_events, (report.season,), "season", 15)
        if rows is not None:
            await consume(rows)
        await self._checkpoint(report)
        if start is not None:
            day = start
            while day <= end and report.requests < self.max_requests:
                rows = await request(self.client.events_on_date, (day.isoformat(),), day.isoformat(), 3)
                if rows is not None:
                    await consume(rows)
                    report.last_completed_date = day.isoformat()
                await self._checkpoint(report)
                day += timedelta(days=1)
        if report.limit_hits:
            report.gaps.append("Response limits reached; premium/second provider and reconciliation required.")
        if report.stats_empty:
            report.gaps.append("Event statistics absent for sampled/imported events; player game statistics require another provider.")
        await self._checkpoint(report, finished=True)
        return report

    async def _checkpoint(self, report, *, finished=False):
        async with self.factory.begin() as session:
            now = datetime.now(timezone.utc) if finished else None
            run = await session.get(CollectionRunRecord, report.run_id)
            if run is None:
                return
            run.finished_at, run.run_metadata = now, asdict(report)
            outcome = await session.scalar(select(SourceOutcomeRecord).where(
                SourceOutcomeRecord.collection_run_id == report.run_id,
                SourceOutcomeRecord.source_id == SOURCE))
            outcome.items_seen, outcome.captures_written = report.events_seen, report.captures_written
            outcome.finished_at, outcome.outcome_metadata = now, asdict(report)

    async def _stats(self, rows, game_id, external_id, run_id, policy, report):
        # Normalize only provider stat fields; never retain descriptions/artwork
        # or pretend that generic player aggregates are game-specific box scores.
        keys = {"idEvent", "idPlayer", "idTeam", "strStat", "strStatName", "strStatType",
                "intHome", "intAway", "intValue", "strValue", "strHome", "strAway", "intStat"}
        values = [{k: v for k, v in row.items() if k in keys and isinstance(v, (str, int, float, type(None)))} for row in rows]
        values = [v for v in values if any(k in v for k in ("strStat", "strStatName", "strStatType"))]
        if not values:
            report.rejected += 1
            return
        observed = datetime.now(timezone.utc)
        body = json.dumps({"statistics": values}, sort_keys=True)
        async with self.factory.begin() as session:
            source = await session.scalar(select(SourceRecord).where(SourceRecord.id == SOURCE).with_for_update())
            if source_policy(source, self.manual) != policy:
                raise ValueError("source policy changed during statistics fetch")
            capture = RawCapture(source_id=SOURCE, external_id="event_stats:" + external_id,
                                 discovered_at=observed, captured_at=observed, content_type="application/json",
                                 text=body, raw_payload=json.dumps(rows, sort_keys=True) if source.retention_policy == "full" else None,
                                 content_hash=hashlib.sha256(body.encode()).hexdigest())
            if await _save_capture(session, source, run_id, capture):
                session.add(TemporalFactRecord(subject_type="game", game_id=game_id, fact_type="provider_event_statistics",
                            value={"statistics": values}, source_id=SOURCE, valid_from=observed,
                            observed_at=observed, available_at=observed,
                            fact_metadata={"provider_key": "thesportsdb", "external_event_id": external_id}))
                report.stats_written += 1
                report.captures_written += 1
