"""Explicit local date update: canonical collection followed by archived ratings.

Job status is deliberately score-opaque. Detailed coverage and run evidence remain
in the existing operator records, never the spoiler-safe consumer status.
"""
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx

from nba_time_machine.db import CollectionRunRecord
from nba_time_machine.ranking.day_processing import process_stored_day
from nba_time_machine.sports.morning import MorningCollector, PublicNBAClient
from nba_time_machine.sports.morning_store import MorningStore
from nba_time_machine.sports.season_foundation_store import ensure_foundation


async def update_day(factory, day, stage):
    foundation = await ensure_foundation(factory, day)
    async with httpx.AsyncClient() as http:
        report = await MorningStore(factory, manual=True).collect(
            MorningCollector(PublicNBAClient(http, max_requests=40), max_games=20), day)
    stage("publishing")
    as_of = datetime.now(timezone.utc)  # Actual processing time, after capture.
    counts = await process_stored_day(factory, day, as_of=as_of)
    async with factory.begin() as session:
        run = await session.get(CollectionRunRecord, UUID(report.run_id))
        if run is not None:
            run.run_metadata = {**run.run_metadata, "season_foundation": foundation, "rating_update": {
                **counts, "as_of": as_of.isoformat()}}
    # Technical failures are distinguished from missing/pending/partial evidence.
    # Never expose a count of completed/scored/pending games in the safe status.
    if report.persistence_errors or counts["failed"]:
        raise ValueError("update_partly_saved")
    if report.discovery is None:
        raise ValueError("sources_unavailable")


class DayUpdateJobs:
    """One bounded application job; durable sports data lives in PostgreSQL."""
    def __init__(self, factory, runner=update_day, timeout=240):
        self.factory, self.runner, self.timeout = factory, runner, timeout
        self.task = None
        self.profile_id = None
        self.result = None

    def start(self, profile_id, day, *, fetch=True):
        if self.task and not self.task.done():
            if self.profile_id == profile_id and self.result["date"] == day.isoformat() and self.fetch == fetch:
                return dict(self.result)  # Double click/retry joins the same job.
            raise ValueError("update_busy")
        self.profile_id = profile_id
        self.fetch = fetch
        self.result = {"job_id": str(uuid4()), "date": day.isoformat(), "state": "collecting" if fetch else "publishing"}
        self.task = asyncio.create_task(self._run(day, fetch=fetch))
        return dict(self.result)

    async def _run(self, day, *, fetch=True):
        try:
            async with asyncio.timeout(self.timeout):
                if fetch:
                    await self.runner(self.factory, day, lambda state: self.result.update(state=state))
                else:
                    counts = await process_stored_day(self.factory, day, as_of=datetime.now(timezone.utc))
                    if counts['failed']:
                        raise ValueError('update_partly_saved')
            self.result.update(state="finished")
        except asyncio.CancelledError:
            self.result.update(state="failed", error="update_interrupted")
            raise
        except TimeoutError:
            self.result.update(state="failed", error="update_time_limit")
        except ValueError as exc:
            code = str(exc)
            self.result.update(state="failed", error=code if code in {
                "morning_source_policy_not_ready", "sports_collection_already_running",
                "sources_unavailable", "update_partly_saved", "day_game_limit",
            } else "update_failed")
        except Exception:
            self.result.update(state="failed", error="update_failed")

    def status(self, profile_id, job_id):
        if self.profile_id != profile_id or not self.result or self.result["job_id"] != str(job_id):
            return None
        return dict(self.result)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
