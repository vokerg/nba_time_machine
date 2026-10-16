"""One bounded morning pass: ESPN primary, independent CBS fallback evidence."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from urllib.parse import quote, urlsplit

import httpx

from nba_time_machine.sports import cbs, espn
from nba_time_machine.sports.morning_models import Evidence, GameRef

SOURCE_IDS = {"espn": "espn-nba-games", "cbs": "cbs-nba-games"}


class FetchError(ValueError):
    """Fixed diagnostic code only, never a response body or exception message."""


@dataclass
class Attempt:
    provider: str
    stage: str
    game: str | None
    status: str
    http_status: int | None = None
    bytes: int = 0
    retry_after: str | None = None


class PublicNBAClient:
    def __init__(self, http: httpx.AsyncClient, *, max_requests=40, interval=1.0,
                 timeout=20.0, max_bytes=4 * 1024 * 1024):
        if not 1 <= max_requests <= 100 or interval < 0 or timeout <= 0 or max_bytes <= 0:
            raise ValueError("invalid_request_limits")
        self.http, self.max_requests, self.interval = http, max_requests, interval
        self.timeout, self.max_bytes = timeout, max_bytes
        self.attempts: list[Attempt] = []
        self.requests = 0
        self.last_request = None
        self.stopped_hosts = set()

    async def fetch(self, provider: str, url: str, stage: str, game=None) -> str:
        host = urlsplit(url).hostname
        allowed = {"espn": "site.api.espn.com", "cbs": "www.cbssports.com"}
        if host != allowed.get(provider) or urlsplit(url).scheme != "https":
            raise ValueError("invalid_provider_url")
        attempt = Attempt(provider, stage, game, "pending")
        self.attempts.append(attempt)
        if host in self.stopped_hosts:
            attempt.status = "host_stopped"
            raise FetchError(attempt.status)
        if self.requests >= self.max_requests:
            attempt.status = "request_budget"
            raise FetchError(attempt.status)
        if self.last_request is not None:
            await asyncio.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
        self.requests += 1
        self.last_request = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout):
                async with self.http.stream("GET", url, follow_redirects=False,
                                            timeout=self.timeout) as response:
                    attempt.http_status = response.status_code
                    if response.status_code != 200:
                        attempt.status = f"http_{response.status_code}"
                        if response.status_code in (401, 403, 429):
                            self.stopped_hosts.add(host)
                            # Diagnostic only; no retry, even when Retry-After is absent.
                            value = response.headers.get("retry-after")
                            attempt.retry_after = value[:80] if value else None
                        raise FetchError(attempt.status)
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        attempt.bytes += len(chunk)
                        if attempt.bytes > self.max_bytes:
                            attempt.status = "response_too_large"
                            raise FetchError(attempt.status)
                        chunks.append(chunk)
                    attempt.status = "ok"
                    return b"".join(chunks).decode("utf-8")
        except (TimeoutError, httpx.TimeoutException):
            attempt.status = "timeout"
            raise FetchError(attempt.status) from None
        except (httpx.HTTPError, UnicodeError):
            attempt.status = "network_or_encoding_error"
            raise FetchError(attempt.status) from None


@dataclass
class GameResult:
    ref: GameRef
    evidence: list[Evidence] = field(default_factory=list)

    def selected(self, family: str) -> Evidence | None:
        return next((e for e in self.evidence if getattr(e, family + "_usable")), None)


@dataclass
class MorningReport:
    day: date
    started_at: datetime
    games: list[GameResult] = field(default_factory=list)
    discovery: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests: int = 0
    run_id: str | None = None
    captures_written: int = 0
    persistence_errors: list[str] = field(default_factory=list)

    def diagnostics(self) -> dict:
        return {
            "day": self.day.isoformat(), "started_at": self.started_at.isoformat(),
            "discovery": self.discovery, "requests": self.requests, "errors": self.errors,
            "run_id": self.run_id, "captures_written": self.captures_written,
            "persistence_errors": self.persistence_errors,
            "games": [{"home": g.ref.home, "away": g.ref.away,
                "pbp_provider": g.selected("pbp").provider if g.selected("pbp") else None,
                "box_provider": g.selected("box").provider if g.selected("box") else None,
                "evidence": [{"provider": e.provider, "game_id": e.external_id,
                    "observed_at": e.observed_at.isoformat(), "status": e.status,
                    "plays": len(e.plays), "players": len(e.players),
                    "has_game_records": e.records is not None,
                    "record_errors": list(e.record_errors),
                    "pbp_errors": list(e.pbp_errors), "box_errors": list(e.box_errors)} for e in g.evidence]
            } for g in self.games],
            "attempts": [asdict(a) for a in self.attempts],
        }


class MorningCollector:
    def __init__(self, client: PublicNBAClient, *, max_games=20, provider="espn"):
        if not 1 <= max_games <= 20 or provider not in ("espn", "cbs"):
            raise ValueError("invalid_collection_limits")
        self.client, self.max_games, self.provider = client, max_games, provider

    async def _refs(self, day: date, report: MorningReport) -> list[GameRef]:
        if self.provider == "espn":
            try:
                text = await self.client.fetch("espn",
                    f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={day:%Y%m%d}", "scoreboard")
                refs = espn.scoreboard(json.loads(text), day)
                report.discovery = "espn"
                return refs
            except (ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError):
                report.errors.append("espn_discovery_failed")
        try:
            text = await self.client.fetch("cbs", f"https://www.cbssports.com/nba/schedule/{day:%Y%m%d}/", "schedule")
            refs = cbs.schedule(text, day)
            report.discovery = "cbs"
            return refs
        except (ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError):
            report.errors.append("cbs_discovery_failed")
            return []

    async def _game(self, ref: GameRef, result: GameResult, report: MorningReport):
        if ref.final is False:
            return
        if ref.provider == "espn":
            try:
                text = await self.client.fetch("espn",
                    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=" + quote(ref.external_id, safe=""),
                    "summary", ref.external_id)
                evidence = espn.summary(json.loads(text), ref, datetime.now(timezone.utc))
                result.evidence.append(evidence)
                if evidence.pbp_usable and evidence.box_usable:
                    return
            except (ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError):
                report.errors.append("espn_game_failed:" + ref.external_id)
        try:
            game_abbr = ref.external_id if ref.provider == "cbs" else ref.cbs_abbr
            text = await self.client.fetch("cbs",
                "https://www.cbssports.com/nba/gametracker/playbyplay/" + quote(game_abbr, safe="") + "/",
                "gametracker", game_abbr)
            result.evidence.append(cbs.gametracker(text, ref, datetime.now(timezone.utc)))
        except (ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError):
            report.errors.append("cbs_game_failed:" + ref.cbs_abbr)

    async def collect(self, day: date, *, game_id: str | None = None) -> MorningReport:
        report = MorningReport(day, datetime.now(timezone.utc))
        refs = await self._refs(day, report)
        if game_id:
            refs = [r for r in refs if r.external_id == game_id or r.cbs_abbr == game_id]
            if not refs:
                report.errors.append("requested_game_not_found")
        if len(refs) > self.max_games:
            report.errors.append("game_budget_exhausted")
        for ref in refs[:self.max_games]:
            result = GameResult(ref)
            report.games.append(result)
            await self._game(ref, result, report)
        report.requests = self.client.requests
        report.attempts = list(self.client.attempts)
        return report
