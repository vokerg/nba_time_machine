"""Operator projection regressions; no network calls or owner database writes."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from nba_time_machine.main import app as consumer
from nba_time_machine.operator import report
from nba_time_machine.operator.app import app, escape_spreadsheet, to_csv


NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def source(**changes):
    values = dict(enabled=True, verification_status="verified", cadence_minutes=60)
    values.update(changes)
    return SimpleNamespace(**values)


def outcome(status="ok", **changes):
    values = dict(status=status, finished_at=NOW - timedelta(minutes=10))
    values.update(changes)
    return SimpleNamespace(**values)


def test_freshness_distinguishes_disabled_failed_idle_stale_and_unknown():
    assert report.freshness(source(enabled=False), outcome(), NOW) == "disabled"
    assert report.freshness(source(verification_status="unverified"), outcome(), NOW) == "unverified"
    assert report.freshness(source(), None, NOW) == "unknown"
    assert report.freshness(source(), outcome("network_error"), NOW) == "failing"
    assert report.freshness(source(), outcome("partial"), NOW) == "failing"
    assert report.freshness(source(), outcome("idle"), NOW) == "idle_recent"
    assert report.freshness(source(), outcome("ok"), NOW) == "recent_check"
    assert report.freshness(source(), outcome("ok", finished_at=NOW - timedelta(minutes=130)), NOW) == "stale"
    assert report.freshness(source(), outcome("ok", finished_at=None), NOW) == "unknown"


def fact(provider, value, when=NOW):
    return SimpleNamespace(source_id=provider, observed_at=when, value=value)


def test_game_families_never_conflate_missing_partial_and_complete():
    empty = report.summarize_evidence([])
    assert empty["play_by_play"]["status"] == "not_collected"
    assert empty["player_box"]["status"] == "not_collected"
    assert empty["team_box"]["status"] == "unsupported"
    partial = report.summarize_evidence([fact("cbs-nba-games", {
        "status": "final", "plays": [], "pbp_errors": ["missing_plays"],
        "players": [{"name": "redacted"}], "box_errors": ["unknown_participation"]
    })])
    assert partial["play_by_play"] == {"status": "partial", "source": "cbs-nba-games"}
    assert partial["player_box"]["status"] == "partial"
    complete = report.summarize_evidence([
        fact("cbs-nba-games", {"status": "final", "plays": [], "pbp_errors": ["missing_plays"]}),
        fact("espn-nba-games", {"status": "final", "plays": [{"id": "1"}], "pbp_errors": [],
                                "players": [{"id": "player"}], "box_errors": []})
    ])
    assert complete["play_by_play"] == {"status": "complete", "source": "espn-nba-games"}
    assert complete["player_box"] == {"status": "complete", "source": "espn-nba-games"}
    pending = report.summarize_evidence([fact("espn", {"status": "pending", "plays": []})])
    assert pending["play_by_play"]["status"] == "not_final"


def test_export_has_only_operational_columns_and_no_spreadsheet_injection():
    assert report.code("http_403") == "http_403"
    assert report.code("Bearer secret?https://example.org?q=token") == "redacted"
    assert escape_spreadsheet("=IMPORTXML('secret')").startswith("'")
    value = to_csv({
        "sources": [{"id": "source", "freshness": "disabled", "last_attempt_at": None, "last_outcome": None}],
        "outcomes": [{"run_id": "run", "source_id": "source", "status": "failed",
                      "finished_at": None, "error_code": "http_403"}],
        "runs": [{"id": "run", "finished_at": None, "started_at": NOW.isoformat(), "collector": "test"}],
        "games": [{"game_id": "game", "day": "2026-10-16", "observation_source": "source",
                   "status": "final", "last_observed_at": NOW.isoformat(),
                   "play_by_play": {"status": "partial"}, "player_box": {"status": "not_collected"}}]
    })
    assert "http_403" in value and "PBP:partial" in value
    assert "Bearer" not in value and "raw_payload" not in value


@pytest.mark.asyncio
async def test_operator_routes_are_local_read_only_and_not_in_consumer():
    # No database or lifespan startup is necessary for these boundary checks.
    transport = httpx.ASGITransport(app=app, client=("192.0.2.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8766") as client:
        assert (await client.get("/")).status_code == 403
        assert (await client.get("/api/report")).status_code == 403
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8766") as client:
        assert (await client.get("/", headers={"Origin": "https://evil.test"})).status_code == 403
        assert (await client.post("/api/report")).status_code == 405
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/operator.js")).status_code == 200
        assert (await client.get("/operator.css")).status_code == 200
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=consumer),
                                 base_url="http://testserver") as client:
        assert (await client.get("/api/report")).status_code == 404
        assert (await client.get("/api/export")).status_code == 404
