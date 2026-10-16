"""Explicit local operator action; previews keep their separate read-only sessions."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from nba_time_machine.sports.morning import MorningCollector, PublicNBAClient
from nba_time_machine.sports.morning_store import MorningStore


async def collect_day(factory, day):
    async with httpx.AsyncClient() as http:
        collector = MorningCollector(PublicNBAClient(http, max_requests=40), max_games=20)
        report = await MorningStore(factory, manual=True).collect(collector, day)
    # Preserve pending discovery even though the existing morning collector intentionally
    # does not fetch/persist unfinished games. Never infer that they are absent.
    return {
        "run_id": report.run_id, "discovery": report.discovery,
        "requests": report.requests, "captures_written": report.captures_written,
        "errors": report.errors + report.persistence_errors,
        "games": [{"home": g.ref.home, "away": g.ref.away,
            "status": "pending" if g.ref.final is False else
                      "complete" if g.selected("pbp") and g.selected("box") else "incomplete",
            "pbp_provider": g.selected("pbp").provider if g.selected("pbp") else None,
            "box_provider": g.selected("box").provider if g.selected("box") else None,
            "errors": sorted({error for e in g.evidence for error in (*e.pbp_errors, *e.box_errors)}),
        } for g in report.games],
        "attempts": [{"provider": a.provider, "stage": a.stage, "status": a.status,
                      "http_status": a.http_status} for a in report.attempts],
    }


class DayVerification:
    """One bounded task/result per local process; persistent run evidence lives in Postgres."""

    def __init__(self, factory):
        self.factory = factory
        self.task = None
        self.result = {"state": "idle"}

    def start(self, day):
        if self.task and not self.task.done():
            return False
        self.result = {"state": "running", "day": day.isoformat(),
                       "job_id": str(uuid4()),
                       "started_at": datetime.now(timezone.utc).isoformat()}
        self.task = asyncio.create_task(self._run(day))
        return True

    async def _run(self, day):
        try:
            async with asyncio.timeout(180):
                details = await collect_day(self.factory, day)
            self.result.update(state="finished", **details)
        except asyncio.CancelledError:
            self.result.update(state="failed", error="collection_interrupted")
            raise
        except TimeoutError:
            self.result.update(state="failed", error="collection_time_limit")
        except ValueError as error:
            code = str(error)
            self.result.update(state="failed", error=code if code in {
                "morning_source_policy_not_ready", "sports_collection_already_running"
            } else "collection_failed")
        except Exception:
            self.result.update(state="failed", error="collection_failed")
        finally:
            self.result["finished_at"] = datetime.now(timezone.utc).isoformat()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
