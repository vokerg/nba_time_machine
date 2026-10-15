"""Bounded daily history collection through existing retention and provenance stores."""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text

from nba_time_machine.db import CollectionRunRecord, SeasonRecord, SourceOutcomeRecord, SourceRecord, TemporalFactRecord
from nba_time_machine.ingestion.contracts import RawCapture
from nba_time_machine.ingestion.runtime import _save_capture
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.sports.standings_history import DayHistory, END, FACT_TYPE, SEASON, SOURCE_ID, START, days, parse_day


@dataclass
class HistoryBatch:
    snapshots: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    captures_written: int = 0
    persistence_errors: int = 0
    run_id: str | None = None

    def diagnostics(self):
        return {"run_id": self.run_id, "days": len(self.snapshots),
            "usable_days": sum(not value.errors for value, _ in self.snapshots),
            "results": sum(len(value.results) for value, _ in self.snapshots),
            "captures_written": self.captures_written, "persistence_errors": self.persistence_errors,
            "errors": self.errors}


async def collect_history(client, start, through):
    if not START <= start <= through <= END or (through - start).days + 1 > client.max_requests:
        raise ValueError("unsupported_or_over_budget_history_range")
    batch = HistoryBatch()
    for day in days(start, through):
        try:
            body = await client.fetch("espn",
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={day:%Y%m%d}", "standings_history", str(day))
            value = parse_day(json.loads(body), day)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            # A newer failed/invalid day cannot leave a formerly good snapshot
            # looking current. Preserve failure coverage, never invent results.
            value = DayHistory(day=day, errors=("history_fetch_or_parse_failed",))
        batch.snapshots.append((value, datetime.now(timezone.utc)))
        if value.errors:
            batch.errors.append({"day": day.isoformat(), "codes": list(value.errors)})
    return batch


async def persist_day(session, source, run_id, value, observed_at):
    season = await session.scalar(select(SeasonRecord).where(SeasonRecord.league == "NBA", SeasonRecord.label == SEASON))
    if season is None:
        season = SeasonRecord(league="NBA", label=SEASON)
        session.add(season)
        await session.flush()
    body = json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    capture = RawCapture(source_id=SOURCE_ID, external_id="standings-day:" + value.day.isoformat(),
        discovered_at=observed_at, captured_at=observed_at, content_type="application/json",
        text=body, content_hash=hashlib.sha256(body.encode()).hexdigest())
    if not await _save_capture(session, source, run_id, capture):
        return False
    session.add(TemporalFactRecord(subject_type="season", season_id=season.id, source_id=SOURCE_ID,
        fact_type=FACT_TYPE, value=value.model_dump(mode="json"),
        valid_from=observed_at, observed_at=observed_at, available_at=observed_at,
        fact_metadata={"day": value.day.isoformat(), "collector_version": "regular-season-history-v1",
            "retrospective_only": True, "source_url":
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={value.day:%Y%m%d}"}))
    return True


async def collect_and_store(factory, client, start, through, *, manual=False):
    async with factory() as lock:
        if not await lock.scalar(text("SELECT pg_try_advisory_xact_lock(734387)")):
            raise ValueError("sports_collection_already_running")
        async with factory() as session:
            policy = source_policy(await session.get(SourceRecord, SOURCE_ID), "espn", manual=manual)
        run_id = uuid4()
        async with factory.begin() as session:
            session.add(CollectionRunRecord(id=run_id, started_at=datetime.now(timezone.utc),
                collector_version="regular-season-history-v1",
                run_metadata={"from": str(start), "through": str(through), "state": "running"}))
        try:
            batch = await collect_history(client, start, through)
            batch.run_id = str(run_id)
            for value, observed_at in batch.snapshots:
                try:
                    async with factory.begin() as session:
                        source = await session.scalar(select(SourceRecord).where(SourceRecord.id == SOURCE_ID).with_for_update())
                        if source_policy(source, "espn", manual=manual) != policy:
                            raise ValueError("source_policy_changed")
                        written = await persist_day(session, source, run_id, value, observed_at)
                    batch.captures_written += int(written)
                except Exception:
                    batch.persistence_errors += 1
                    batch.errors.append({"day": str(value.day), "codes": ["history_persist_or_policy_failed"]})
            async with factory.begin() as session:
                session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=SOURCE_ID,
                    status="partial" if batch.errors or batch.persistence_errors else "ok" if batch.captures_written else "idle",
                    items_seen=len(batch.snapshots), captures_written=batch.captures_written,
                    finished_at=datetime.now(timezone.utc), outcome_metadata={**batch.diagnostics(),
                        "attempts": [vars(a) for a in client.attempts]}))
                run = await session.get(CollectionRunRecord, run_id)
                run.finished_at = datetime.now(timezone.utc)
                run.run_metadata = batch.diagnostics()
            return batch
        except BaseException:
            async with factory.begin() as session:
                run = await session.get(CollectionRunRecord, run_id)
                run.finished_at = datetime.now(timezone.utc)
                run.run_metadata = {"state": "interrupted", "from": str(start), "through": str(through)}
            raise
