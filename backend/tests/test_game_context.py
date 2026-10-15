from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from history_fixtures import scoreboard
from nba_time_machine.ranking.game_context import reconstruct
from nba_time_machine.sports.history_collection import collect_history
from nba_time_machine.sports.morning import PublicNBAClient
from nba_time_machine.sports.standings_history import CONFERENCES, DayHistory, Result, START, TEAM_NAMES, days, parse_day
from nba_time_machine.workbench.app import CANDIDATE_CONFIG
from nba_time_machine.workbench.calculations import TuningConfig, candidate_preview
from nba_time_machine.workbench.context import ContextSettings, context_preview


def full_history(count=20):
    teams = list(TEAM_NAMES)
    return [DayHistory(day=day, results=tuple(Result(external_id=str(100000 + n * 15 + i),
        tip=datetime.combine(day, time(23), timezone.utc), home=teams[i], away=teams[i + 15],
        home_score=110, away_score=100) for i in range(15)))
        for n, day in enumerate(days(START, START + timedelta(days=count - 1)))]


def context(count=20, home="ATL", away="BOS"):
    standings = reconstruct(full_history(count), START + timedelta(days=count))
    return {"status": "available", "reason": "Fixture", "standings": standings,
        "home": next(r for r in standings if r["team"] == home),
        "away": next(r for r in standings if r["team"] == away)}


def test_scoreboard_counts_only_regular_season_and_excludes_cup_championship():
    day = START
    good = parse_day(scoreboard(day), day)
    assert good.results[0].away == "NYK" and not good.errors
    assert CONFERENCES['NYK'] == 'East' and sum(v == 'East' for v in CONFERENCES.values()) == 15
    for kind, competition_type in [(1, "1"), (3, "1"), (2, "39")]:
        value = parse_day(scoreboard(day, kind=kind, competition_type=competition_type), day)
        assert value.excluded == 1 and not value.results
    assert parse_day(scoreboard(day, completed=False), day).errors
    assert parse_day(scoreboard(day), day + timedelta(days=1)).errors


def test_pending_malformed_wrong_calendar_and_duplicate_teams_cannot_fake_complete_day():
    p = scoreboard(START)
    p['events'][0]['competitions'][0]['competitors'][0]['score'] = True
    assert parse_day(p, START).errors
    p = scoreboard(START)
    p['events'].append(p['events'][0])
    with pytest.raises(ValueError):
        parse_day(p, START)
    with pytest.raises(ValueError):
        DayHistory(day=date(2024, 10, 21))


def test_records_preserve_ties_and_require_every_day_before_target():
    h = full_history()
    rows = reconstruct(h, START + timedelta(days=20))
    assert len(rows) == 30
    assert len([r for r in rows if r['league_rank'] == 1]) == 15
    assert all(r['games_played'] == 20 for r in rows)
    with pytest.raises(ValueError):
        reconstruct(h[:-1], START + timedelta(days=20))
    # Target-day/later results cannot enter an earlier reconstruction.
    with pytest.raises(ValueError):
        reconstruct(h, START + timedelta(days=19))
    duplicate = h[1].model_copy(update={'results': (h[1].results[0].model_copy(update={'external_id': h[0].results[0].external_id}),)})
    with pytest.raises(ValueError):
        reconstruct([h[0], duplicate], START + timedelta(days=2))


def test_both_strong_teams_gain_more_credit_than_strong_vs_weak_and_early_sample_is_discounted():
    settings = ContextSettings()
    strong = context_preview(context(), settings)
    weak = context_preview(context(home='ATL', away='WAS'), settings)
    early = context_preview(context(4), settings)
    assert strong['bonus'] > weak['bonus']
    assert early['bonus'] < strong['bonus'] <= settings.max_bonus
    assert strong['calculation']['race_magnitude'] == 0  # November is not a late-season race.
    assert context_preview(context(2), settings)['bonus'] is None
    assert context_preview({'status':'missing'}, settings)['bonus'] is None


def test_late_standings_race_is_conditional_on_same_conference_and_has_visible_inputs():
    c = context()
    # Synthetic late-season, middle-of-conference close race around 6th.
    for index, row in enumerate(r for r in c['standings'] if r['conference'] == 'East'):
        row.update(games_played=70, wins=40-index, losses=30+index, conference_rank=index+1)
    c['home'] = next(r for r in c['standings'] if r['conference'] == 'East' and r['conference_rank'] == 6)
    c['away'] = next(r for r in c['standings'] if r['conference'] == 'East' and r['conference_rank'] == 7)
    result = context_preview(c, ContextSettings())
    assert result['calculation']['boundary_gap'] == 0
    assert result['calculation']['race_magnitude'] > 0
    c['away'] = {**c['away'], 'conference':'West'}
    assert context_preview(c, ContextSettings())['calculation']['race_magnitude'] == 0


def test_v3_is_explicit_legacy_compatible_and_reconciles_uncapped_total():
    from test_entertainment_features import game, candidate
    from nba_time_machine.ranking.entertainment_features import entertainment_measurements
    from nba_time_machine.ranking.morning_features import trajectory_features
    e = game()
    config = TuningConfig.model_validate_json(CANDIDATE_CONFIG.with_name('entertainment-context-v3.json').read_text())
    result = candidate_preview(trajectory_features(e), entertainment_measurements(e), config, context())
    old = candidate_preview(trajectory_features(e), entertainment_measurements(e), candidate())
    assert result['before_cap'] == old['before_cap'] + result['context_bonus']
    assert result['score'] == round(min(10, result['before_cap']), 4)
    missing = candidate_preview(trajectory_features(e), entertainment_measurements(e), config, {'status':'missing'})
    assert missing['coverage'] == 'partial' and missing['context_bonus'] is None
    assert missing['score'] == old['score']
    with pytest.raises(ValidationError):
        TuningConfig.model_validate({**config.model_dump(), 'schema_version':2})
    with pytest.raises(ValidationError):
        ContextSettings(win_pct_floor=.8, win_pct_peak=.6)


@pytest.mark.asyncio
async def test_history_requests_are_bounded_and_one_failure_does_not_discard_other_days():
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=scoreboard(START + timedelta(days=1)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = PublicNBAClient(http, max_requests=2, interval=0)
        batch = await collect_history(client, START, START + timedelta(days=1))
        assert len(batch.snapshots) == 2 and len(batch.errors) == 1
        assert not batch.snapshots[1][0].errors
        assert len(calls) == 2
        with pytest.raises(ValueError):
            await collect_history(client, START, START + timedelta(days=2))
        assert len(calls) == 2
