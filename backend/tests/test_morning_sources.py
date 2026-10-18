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


def test_missing_boxes_keep_pbp_and_do_not_invent_participant_resolution():
    data = summary()
    data["plays"][0]["participants"] = [dict(athlete=dict(id="1001"))]
    data.pop("boxscore")
    e = parsed(data)
    assert e.pbp_usable and not e.box_usable
    assert "participant_box_match_unverified" in e.notes


def test_overtime_boundaries_and_clocks_require_tied_regulation():
    data = summary()
    # Extend the synthetic fixture to two overtimes, tying regulation and OT1.
    home, away = data["header"]["competitions"][0]["competitors"]
    home.update(score="6", linescores=[dict(displayValue="1") for _ in range(6)])
    away.update(score="5", linescores=[dict(displayValue=str(i)) for i in (1, 1, 1, 1, 1, 0)])
    data["plays"].pop()  # End Game moves to the last OT.
    end4 = data["plays"].pop()
    extra = copy.deepcopy(data["plays"][-1])
    extra.update(id=EVENT + "900", homeScore=4, awayScore=4)
    extra["clock"] = dict(displayValue="10:00")
    data["plays"].append(extra)
    end4["awayScore"] = 4
    data["plays"].append(end4)
    for p in (5, 6):
        for index, (h, a, clock, kind) in enumerate([(p, p - 1, "4:00", "1"), (p, min(p, 5), "3:00", "1"), (p, min(p, 5), "0.0", "412")]):
            if p == 6 and index == 1:
                continue
            row = copy.deepcopy(extra)
            row.update(id=EVENT + str(1000 + p * 10 + index), homeScore=h, awayScore=a,
                       scoreValue=0 if kind == "412" else 1, scoringPlay=kind != "412")
            row.update(period=dict(number=p), clock=dict(displayValue=clock), type=dict(id=kind))
            data["plays"].append(row)
    end = copy.deepcopy(data["plays"][-1])
    end.update(id=EVENT + "9999", type=dict(id="402"))
    data["plays"].append(end)
    for team, pts in zip(data["boxscore"]["players"], (5, 6)):
        stats = team["statistics"][0]["athletes"][0]["stats"]
        stats[1], stats[4] = str(pts), f"{pts}-{pts}"
    assert parsed(data).pbp_usable
    data["plays"][-3]["clock"]["displayValue"] = "5:01"
    assert "invalid_period_clock" in parsed(data).pbp_errors


def test_cbs_blank_rows_are_unknown_and_responsive_duplicates_are_deduplicated():
    html = cbs_html()
    section = html[html.index('<div id="player-stats-away"'):html.index('<div id="player-stats-home"')]
    assert len(cbs.gametracker(html + section, cbs.ref_from_abbr("NBA_20261013_GS@LAL"), NOW).players) == 2
    blank = '<tr><td><a href="/nba/players/999/unknown/">Unknown</a></td>' + '<td>-</td>' * 15 + '</tr>'
    html = html.replace('</table></div>', blank + '</table></div>', 1)
    e = cbs.gametracker(html, cbs.ref_from_abbr("NBA_20261013_GS@LAL"), NOW)
    assert not e.box_usable and next(p for p in e.players if p.external_id == "999").did_not_play is None


def test_game_and_response_identity_mismatches_fail_closed():
    data = summary()
    ref = espn.scoreboard(scoreboard(data), DAY)[0]
    data["header"]["id"] = "wrong"
    with pytest.raises(ValueError, match="wrong_espn_game"):
        espn.summary(data, ref, NOW)


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
async def test_complete_primary_does_not_request_cbs():
    def handler(req):
        assert req.url.host == "site.api.espn.com"
        return httpx.Response(200, json=scoreboard() if "scoreboard" in req.url.path else summary())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        report = await MorningCollector(PublicNBAClient(http, interval=0)).collect(DAY)
    assert report.requests == 2 and report.games[0].selected("pbp").provider == "espn"


@pytest.mark.asyncio
async def test_malformed_game_does_not_abort_other_matchups():
    good = summary(event="123456780", home_id="2")
    good["header"]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "BOS"
    board = scoreboard()
    board["events"].extend(scoreboard(good)["events"])
    def handler(req):
        if "scoreboard" in req.url.path:
            return httpx.Response(200, json=board)
        if req.url.params.get("event") == "123456780":
            return httpx.Response(200, json=good)
        return httpx.Response(200, json={"invalid": True})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        report = await MorningCollector(PublicNBAClient(http, interval=0)).collect(DAY)
    assert len(report.games) == 2
    assert report.games[0].selected("pbp") is None
    assert report.games[1].selected("pbp").external_id == "123456780"


@pytest.mark.asyncio
async def test_total_request_deadline_includes_slow_body():
    import asyncio
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"start"
            await asyncio.sleep(0.05)
            yield b"finish"
    def handler(req):
        return httpx.Response(200, stream=SlowBody())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PublicNBAClient(http, timeout=0.01)
        with pytest.raises(FetchError, match="timeout"):
            await client.fetch("espn", "https://site.api.espn.com/test", "test")
    assert client.attempts[0].status == "timeout"


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


def scoring_fixture():
    """Synthetic explicit scoring teams, independent of reported running states."""
    data = summary()
    previous = (0, 0)
    home, away = data['header']['competitions'][0]['competitors']
    for row in data['plays']:
        if row['scoringPlay']:
            row['team'] = {'id': home['id'] if row['homeScore'] > previous[0] else away['id']}
        previous = row['homeScore'], row['awayScore']
    return data


def test_stale_running_states_reconstruct_only_from_explicit_reconciled_actions():
    from nba_time_machine.sports.morning_models import Evidence, assess
    from nba_time_machine.ranking.morning_features import trajectory_features
    data = scoring_fixture()
    original = parsed(data)
    # Stale timeout/end state after a basket: preserve the source claim.
    data['plays'][3]['homeScore'] = 0
    recovered = parsed(data)
    assert recovered.pbp_usable and recovered.box_usable
    assert recovered.trajectory_basis == 'scoring_actions_v1'
    assert 'score_regression' in recovered.reported_pbp_errors
    assert recovered.plays[3].reported_home == 0
    assert recovered.plays[3].home == 1
    assert recovered.observed_at == NOW
    assert trajectory_features(recovered) == trajectory_features(original)
    assert assess(Evidence.model_validate(recovered.model_dump())).pbp_usable
    corrupt = list(recovered.plays)
    corrupt[1] = corrupt[1].model_copy(update={'scoring_team_id': 'unknown'})
    assert 'invalid_scoring_action_reconstruction' in assess(
        recovered.model_copy(update={'plays': tuple(corrupt)})).pbp_errors


@pytest.mark.parametrize('fault', ['missing_team', 'unknown_team', 'points', 'unknown_scoring',
                                   'clock', 'duplicate', 'boundary', 'missing_end', 'period_total'])
def test_reconstruction_does_not_hide_missing_or_conflicting_evidence(fault):
    data = scoring_fixture()
    data['plays'][3]['homeScore'] = 0
    if fault == 'missing_team':
        data['plays'][1].pop('team')
    elif fault == 'unknown_team':
        data['plays'][1]['team']['id'] = 'unknown'
    elif fault == 'points':
        data['plays'][1]['scoreValue'] = 2
    elif fault == 'unknown_scoring':
        data['plays'][0].pop('scoringPlay')
    elif fault == 'clock':
        data['plays'][2]['clock']['displayValue'] = '11:30'
    elif fault == 'duplicate':
        data['plays'][2]['id'] = data['plays'][1]['id']
    elif fault == 'boundary':
        data['plays'][0]['homeScore'] = 1
    elif fault == 'missing_end':
        data['plays'].pop()
    else:
        h = data['header']['competitions'][0]['competitors'][0]
        h['linescores'][0]['displayValue'] = '0'
        h['linescores'][1]['displayValue'] = '2'
    e = parsed(data)
    assert not e.pbp_usable
    assert e.trajectory_basis == 'provider_scores'
    assert all(p.reported_home is None for p in e.plays)


@pytest.mark.asyncio
async def test_cbs_canonical_redirect_is_bounded_and_counts_requests():
    url = 'https://www.cbssports.com/nba/gametracker/playbyplay/NBA_20261013_GS%40LAL/'
    calls = []
    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(301, headers={'Location': url.lower()})
        return httpx.Response(200, text=cbs_html())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PublicNBAClient(http, interval=0)
        assert await client.fetch('cbs', url, 'gametracker') == cbs_html()
        assert client.requests == 2
        assert [a.status for a in client.attempts] == ['redirected', 'ok']
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        calls.clear()
        client = PublicNBAClient(http, interval=0, max_requests=1)
        with pytest.raises(FetchError, match='request_budget'):
            await client.fetch('cbs', url, 'gametracker')
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('location', [
    'http://www.cbssports.com/nba/gametracker/playbyplay/nba_20261013_gs%40lal/',
    'https://other.invalid/nba/gametracker/playbyplay/nba_20261013_gs%40lal/',
    '/nba/gametracker/playbyplay/nba_20261014_gs%40lal/',
    '/nba/gametracker/playbyplay/nba_20261013_gs%40lal/?token=abc',
    '/nba/gametracker/playbyplay/nba_20261013_gs%40lal/#fragment',
])
async def test_cbs_redirect_cannot_change_provider_game_or_access_method(location):
    def handler(req):
        return httpx.Response(301, headers={'Location': location})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PublicNBAClient(http, interval=0)
        with pytest.raises(FetchError, match='http_301'):
            await client.fetch('cbs', 'https://www.cbssports.com/nba/gametracker/playbyplay/NBA_20261013_GS%40LAL/', 'gametracker')
        assert client.requests == 1


@pytest.mark.asyncio
async def test_cbs_redirect_loop_is_not_followed_twice():
    def handler(req):
        return httpx.Response(301, headers={'Location': '/nba/gametracker/playbyplay/nba_20261013_gs%40lal/'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PublicNBAClient(http, interval=0)
        with pytest.raises(FetchError, match='http_301'):
            await client.fetch('cbs', 'https://www.cbssports.com/nba/gametracker/playbyplay/NBA_20261013_GS%40LAL/', 'gametracker')
        assert client.requests == 2


@pytest.mark.asyncio
async def test_phoenix_fallback_uses_cbs_schedule_identity_not_espn_abbreviation():
    data = summary()
    home, away = data['header']['competitions'][0]['competitors']
    home['team']['abbreviation'], away['team']['abbreviation'] = 'PHX', 'UTA'
    data['plays'].pop()  # Force the independent fallback.
    backup = cbs_html(abbr='NBA_20261013_UTA@PHO').replace('LAL', 'PHO').replace('GS', 'UTA')
    calls = []
    def handler(req):
        calls.append(req)
        if req.url.host == 'site.api.espn.com':
            return httpx.Response(200, json=scoreboard(data) if 'scoreboard' in req.url.path else data)
        assert 'UTA%40PHO/' in str(req.url)
        return httpx.Response(200, text=backup)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        r = await MorningCollector(PublicNBAClient(http, interval=0)).collect(DAY)
    assert r.games[0].selected('box').provider == 'espn'
    assert r.games[0].evidence[-1].provider == 'cbs'
    assert r.games[0].evidence[-1].ref.home == 'PHX'
    assert len(calls) == 3 and not r.errors
