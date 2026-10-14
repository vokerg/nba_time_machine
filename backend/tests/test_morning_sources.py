import copy
from datetime import date, datetime, timezone

import httpx
import pytest

from morning_fixtures import EVENT, cbs_html, scoreboard, summary
from nba_time_machine.sports import cbs, espn
from nba_time_machine.sports.morning import FetchError, MorningCollector, PublicNBAClient

DAY = date(2026, 10, 13)
NOW = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)


def parsed(payload=None):
    data = payload or summary()
    ref = espn.scoreboard(scoreboard(data), DAY)[0]
    return espn.summary(data, ref, NOW)


def test_espn_normalizes_complete_periods_boxes_and_conservative_timestamps():
    e = parsed()
    assert e.pbp_usable and e.box_usable
    assert e.observed_at == NOW and e.source_end_at < NOW
    assert e.ref.home == "LAL" and e.ref.away == "GSW"
    assert e.season == "2026-2027" and e.game_type == "preseason"
    assert e.players[0].minutes_precision == "rounded_minute"
    assert "observed_at" not in e.retained_value()
    assert "final_at" not in e.retained_value()


@pytest.mark.parametrize("change,error", [
    (lambda d: d["plays"].pop(), "missing_game_end"),
    (lambda d: d["plays"].__setitem__(2, copy.deepcopy(d["plays"][1])), "duplicate_play_ids"),
    (lambda d: d["plays"][1]["clock"].update(displayValue="12:01"), "invalid_play_schema"),
    (lambda d: d["plays"][2].update(homeScore=0), "score_regression"),
    (lambda d: d["plays"][2]["clock"].update(displayValue="11:01"), "clock_order"),
    (lambda d: d["plays"][0].update(participants=[dict(athlete=dict(id="999"))]), "unresolved_participant"),
])
def test_bad_pbp_does_not_discard_valid_boxes(change, error):
    data = summary()
    change(data)
    e = parsed(data)
    assert not e.pbp_usable and error in e.pbp_errors
    assert e.box_usable


def test_bad_boxes_do_not_discard_valid_pbp():
    data = summary()
    data["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][1] = "99"
    e = parsed(data)
    assert e.pbp_usable and not e.box_usable
    assert "player_point_totals_mismatch" in e.box_errors


def test_returned_order_is_preserved_despite_sequence_and_wallclock_reversals():
    data = summary()
    data["plays"][1]["sequenceNumber"] = "9999"
    data["plays"][1]["wallclock"] = "2026-10-14T04:01:00Z"
    assert parsed(data).pbp_usable


def test_cbs_boxes_work_but_absent_play_ids_never_become_complete_pbp():
    ref = cbs.ref_from_abbr("NBA_20261013_GS@LAL")
    e = cbs.gametracker(cbs_html(), ref, NOW)
    assert e.box_usable, e.box_errors
    assert not e.pbp_usable and "missing_play_ids" in e.pbp_errors
    assert all(p.external_id is None for p in e.plays)
    assert e.source_end_at is None


def test_wrong_matchup_and_wrong_day_are_rejected():
    ref = espn.scoreboard(scoreboard(), DAY)[0]
    data = summary()
    data["header"]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "BOS"
    with pytest.raises(ValueError, match="wrong_matchup"):
        espn.summary(data, ref, NOW)
    with pytest.raises(ValueError, match="wrong_day"):
        espn.scoreboard(scoreboard(), date(2026, 10, 14))
    with pytest.raises(ValueError, match="wrong_cbs_matchup"):
        cbs.gametracker(cbs_html(abbr="NBA_20261013_GS@BOS"), ref, NOW)


@pytest.mark.asyncio
async def test_summary_failure_falls_back_and_retains_primary_failure():
    def handler(req):
        if "scoreboard" in req.url.path:
            return httpx.Response(200, json=scoreboard())
        if "summary" in req.url.path:
            return httpx.Response(503)
        return httpx.Response(200, text=cbs_html())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        report = await MorningCollector(PublicNBAClient(http, interval=0)).collect(DAY)
    game = report.games[0]
    assert game.selected("box").provider == "cbs"
    assert game.selected("pbp") is None
    assert "espn_game_failed:" + EVENT in report.errors
    assert report.requests == 3


@pytest.mark.asyncio
async def test_partial_primary_keeps_good_family_when_cbs_is_down():
    data = summary()
    data["plays"].pop()
    def handler(req):
        if "scoreboard" in req.url.path:
            return httpx.Response(200, json=scoreboard(data))
        if "summary" in req.url.path:
            return httpx.Response(200, json=data)
        return httpx.Response(403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        report = await MorningCollector(PublicNBAClient(http, interval=0)).collect(DAY)
    assert report.games[0].selected("box").provider == "espn"
    assert report.games[0].selected("pbp") is None


@pytest.mark.asyncio
async def test_discovery_fallback_uses_only_requested_date_and_deduplicates_links():
    link = '<a href="/nba/gametracker/live/NBA_20261013_GS%40LAL/">Game</a>'
    def handler(req):
        if req.url.host == "site.api.espn.com":
            return httpx.Response(403)
        if "/schedule/" in req.url.path:
            return httpx.Response(200, text=link + link + link.replace("20261013", "20261012"))
        return httpx.Response(200, text=cbs_html())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        r = await MorningCollector(PublicNBAClient(http, interval=0)).collect(DAY)
    assert r.discovery == "cbs" and len(r.games) == 1
    assert r.games[0].selected("box").provider == "cbs"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_access_denials_stop_further_requests_to_that_host(status):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, headers={"Retry-After": "120"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PublicNBAClient(http, interval=0)
        for _ in range(2):
            with pytest.raises(FetchError):
                await client.fetch("espn", "https://site.api.espn.com/test", "test")
    assert len(calls) == 1 and client.attempts[-1].status == "host_stopped"


@pytest.mark.asyncio
async def test_budget_byte_cap_and_redirects_are_enforced():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, content=b"x" * 30)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PublicNBAClient(http, max_requests=1, max_bytes=10, interval=0)
        with pytest.raises(FetchError, match="response_too_large"):
            await client.fetch("espn", "https://site.api.espn.com/test", "test")
        with pytest.raises(FetchError, match="request_budget"):
            await client.fetch("cbs", "https://www.cbssports.com/test", "test")
        assert len(calls) == 1
    def redirect(req):
        return httpx.Response(302, headers={"Location": "https://other.invalid"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect), follow_redirects=True) as http:
        with pytest.raises(FetchError, match="http_302"):
            await PublicNBAClient(http).fetch("espn", "https://site.api.espn.com/test", "test")
