"""Synthetic complete rankings; never copied publisher ordering."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from nba_time_machine.ranking.player_rankings import RankingImport, map_players
from nba_time_machine.ranking.star_power import StarSettings, rank_value, star_preview
from nba_time_machine.sports.morning_models import Evidence, GameRef, PlayerBox, Team
from nba_time_machine.workbench.calculations import TuningConfig, candidate_preview
from nba_time_machine.ranking.entertainment_features import entertainment_measurements
from nba_time_machine.ranking.morning_features import TrajectoryFeatures

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def ranking():
    return RankingImport.model_validate({'ranking_version': 'synthetic-v1', 'season': '2026-2027',
        'publication_status': 'unknown', 'permission_reference': 'synthetic-test-only',
        'players': [{'rank': i, 'name': f'Fixture Player {i}'} for i in range(1, 101)]})


def catalog():
    return [{'espn_id': str(i), 'name': f'Fixture Player {i}', 'team': 'BOS', 'fact_id': 'synthetic-fact'} for i in range(1, 101)]


def snapshot():
    r = ranking()
    return {**r.model_dump(mode='json'), 'status': 'available', 'players': map_players(r, catalog()),
        'observed_at': (NOW - timedelta(days=1)).isoformat(), 'available_at': (NOW - timedelta(days=1)).isoformat()}


def evidence(home_rank=1, away_rank=2):
    players = []
    for team, rank, offset in [('1', home_rank, 1000), ('2', away_rank, 2000)]:
        # Five players × 48 minutes proves the full team family in this fixture.
        for j in range(5):
            key = str(rank) if j == 0 else str(offset+j)
            players.append(PlayerBox(external_id=key, team_id=team, name='Player '+key,
                did_not_play=False, minutes=48, minutes_precision='second', statistics={'PTS':20}))
    ref = GameRef(provider='espn', external_id='123', day=NOW.date(), home='BOS', away='NYK', scheduled_at=NOW)
    return Evidence(provider='espn', external_id='123', ref=ref, observed_at=NOW+timedelta(hours=4),
        season='2026-2027', game_type='regular_season', status='final', players=tuple(players),
        home=Team(external_id='1', abbreviation='BOS', name='Boston', score=100, periods=(25,25,25,25)),
        away=Team(external_id='2', abbreviation='NYK', name='New York', score=99, periods=(25,25,25,24)))


def replace_player(e, key, **updates):
    return e.model_copy(update={'players': tuple(p.model_copy(update=updates) if p.external_id==str(key) else p for p in e.players)})


def test_full_100_validation_and_name_identity():
    r = ranking()
    assert len(map_players(r, catalog())) == 100
    assert all(p['mapping_status']=='matched' for p in map_players(r,catalog()))
    for rows in [r.players[:99], (r.players[0],)*100]:
        with pytest.raises(ValidationError): RankingImport.model_validate({**r.model_dump(), 'players': rows})
    c = catalog()+[{'espn_id':'999', 'name':'Fixture Player 1', 'team':'NYK','fact_id':'other'}]
    assert map_players(r,c)[0]['mapping_status']=='ambiguous'
    p=r.players[0].model_copy(update={'team':'BOS'})
    assert map_players(r.model_copy(update={'players':(p,)+r.players[1:]}),c)[0]['espn_id']=='1'
    p=p.model_copy(update={'espn_id':'1','team':'LAL'})
    assert map_players(r.model_copy(update={'players':(p,)+r.players[1:]}),c)[0]['espn_id']=='1' # explicit validated ID survives trade


def test_accents_aliases_and_injury_absence():
    r=ranking(); c=catalog(); c[0]['name']='Nikola Jokić'
    p=r.players[0].model_copy(update={'name':'Nikola Jokic'})
    assert map_players(r.model_copy(update={'players':(p,)+r.players[1:]}),c)[0]['espn_id']=='1'
    p=p.model_copy(update={'name':'N. Jokic'})
    assert map_players(r.model_copy(update={'players':(p,)+r.players[1:]}),c)[0]['mapping_status']=='unmatched'
    p=p.model_copy(update={'espn_id':'1','espn_name_alias':'Nikola Jokic','alias_review':'reviewed alias fixture'})
    assert map_players(r.model_copy(update={'players':(p,)+r.players[1:]}),c)[0]['espn_id']=='1'
    result=star_preview(evidence(900,901),snapshot(),StarSettings())
    assert result['metric']==result['bonus']==0
    assert 'injury' in result['unranked_note']


def test_elite_both_teams_and_minutes_dnp_unknown():
    s=StarSettings(); e=evidence()
    both=star_preview(e,snapshot(),s)
    one=star_preview(evidence(1,900),snapshot(),s)
    ordinary=star_preview(evidence(80,81),snapshot(),s)
    assert 0 < ordinary['metric'] < one['metric'] < both['metric'] <= 1
    limited=replace_player(e,1,minutes=3)
    # Bench player absorbs the remaining minutes; no per-minute extrapolation.
    bench=limited.players[1].model_copy(update={'external_id':'9999','minutes':45})
    limited=limited.model_copy(update={'players': limited.players+(bench,)})
    value=star_preview(limited,snapshot(),s)
    assert value['teams'][0]['coverage']=='complete'
    assert value['teams'][0]['players'][0]['minutes_factor']==.1
    assert value['bonus']<both['bonus']
    for dnp, status in [(True,'dnp'),(False,'zero_minutes')]:
        absent=replace_player(limited,1,did_not_play=dnp,minutes=0,statistics={})
        absent=absent.model_copy(update={'players':absent.players+(bench.model_copy(update={'external_id':'9998','minutes':3}),)})
        a=star_preview(absent,snapshot(),s)
        assert a['teams'][0]['players'][0]['participation']==status
        assert a['teams'][0]['players'][0]['contribution']==0
    unknown=star_preview(replace_player(e,1,did_not_play=None,minutes=None),snapshot(),s)
    assert unknown['bonus'] is None
    assert unknown['teams'][0]['coverage']=='incomplete' and unknown['teams'][1]['coverage']=='complete'


def test_three_stars_diminishing_no_many_players_inflation():
    e=evidence(); rows=list(e.players)
    for i, rank in [(1,3),(2,4),(3,5)]: rows[i]=rows[i].model_copy(update={'external_id':str(rank)})
    v=star_preview(e.model_copy(update={'players':tuple(rows)}),snapshot(),StarSettings())
    home=v['teams'][0]
    assert home['raw_total']==1.55 and home['normalized']==1
    assert [p['slot_weight'] for p in home['players']]==[1,.4,.15,0]
    assert v==star_preview(e.model_copy(update={'players':tuple(rows)}),snapshot(),StarSettings())


def test_missing_future_partial_and_caps():
    e=evidence(); s=StarSettings()
    assert star_preview(e,None,s)['bonus'] is None
    future={**snapshot(),'available_at':(NOW+timedelta(seconds=1)).isoformat()}
    assert star_preview(e,future,s)['bonus'] is None
    incomplete=e.model_copy(update={'players':tuple(p for p in e.players if p.team_id=='1')})
    v=star_preview(incomplete,snapshot(),s)
    assert v['bonus'] is None and v['teams'][0]['coverage']=='complete' and v['teams'][1]['coverage']=='incomplete'
    snap=snapshot();snap['players'][99]['mapping_status']='unmatched'
    assert star_preview(e,snap,s)['bonus'] is None
    assert star_preview(e,snapshot(),s)['bonus']<=1.5
    assert rank_value(5,s)>rank_value(20,s)>rank_value(50,s)>rank_value(100,s)
    with pytest.raises(ValidationError): StarSettings(top20_end=4)
    with pytest.raises(ValidationError): StarSettings(third_weight=.8,second_weight=.1)


def test_v5_cap_legacy_configs_and_reproducibility():
    configs=[TuningConfig.model_validate_json(p.read_text()) for p in (ROOT/'config/ranking').glob('*.json')]
    c=next(c for c in configs if c.schema_version==5)
    e=evidence(); measurement=entertainment_measurements(e)
    metrics=TrajectoryFeatures(clutch_ms=300000,lead_changes=20,winner_max_deficit=25,overtime_periods=3)
    star=star_preview(e,snapshot(),c.star)
    value=candidate_preview(metrics,measurement,c,None,star)
    assert value['score']==10 and value['star_bonus']>0 and value['cap_adjustment']<0
    assert value==candidate_preview(metrics,measurement,c,None,star)
    assert candidate_preview(metrics,measurement,c)['star_bonus'] is None
    for cfg in configs:
        if cfg.schema_version<5:
            assert 'star_bonus' not in candidate_preview(metrics,measurement,cfg)


def test_espn_partial_team_preserves_other_team_and_unknown_rows():
    from morning_fixtures import summary, scoreboard
    from nba_time_machine.sports import espn
    from integration.test_morning_persistence import DAY, NOW
    data=summary()
    original=espn.summary(data,espn.scoreboard(scoreboard(data),DAY)[0],NOW)
    first_team=str(data['boxscore']['players'][0]['team']['id'])
    other_team=str(data['boxscore']['players'][1]['team']['id'])
    data['boxscore']['players'][0]['statistics'][0]['athletes'][0].pop('didNotPlay')
    parsed=espn.summary(data,espn.scoreboard(scoreboard(data),DAY)[0],NOW)
    assert parsed.box_team_errors[first_team]
    assert any(p.did_not_play is None for p in parsed.players if p.team_id==first_team)
    assert [p for p in parsed.players if p.team_id==other_team]==[p for p in original.players if p.team_id==other_team]
    assert other_team not in parsed.box_team_errors
    data['boxscore']['players'][0]['statistics']=[]
    parsed=espn.summary(data,espn.scoreboard(scoreboard(data),DAY)[0],NOW)
    assert parsed.box_team_errors[first_team] and any(p.team_id==other_team for p in parsed.players)


def test_conflicting_dnp_missing_minutes_unknown_ids_and_invalid_snapshots():
    e=evidence(); snap=snapshot(); s=StarSettings()
    for changes in ({'did_not_play':True}, {'minutes':None}, {'minutes':99}):
        v=star_preview(replace_player(e,1,**changes),snap,s)
        assert v['bonus'] is None
    dup=e.model_copy(update={'players':e.players+(e.players[0],)})
    assert star_preview(dup,snap,s)['bonus'] is None
    snap['players']=snap['players'][:99]
    assert star_preview(e,snap,s)['bonus'] is None
    # Missing minutes cannot hide inside a tolerance based on DNP/bench count.
    assert star_preview(replace_player(e,1,minutes=47),snapshot(),s)['bonus'] is None
    assert star_preview(replace_player(e,1,minutes_precision='unknown'),snapshot(),s)['bonus'] is None
    with pytest.raises(ValidationError):
        RankingImport.model_validate({**ranking().model_dump(),'observed_at':NOW})


def test_duplicate_resolved_identities_and_unreviewed_aliases_fail_closed():
    r=ranking(); rows=list(r.players)
    rows[1]=rows[1].model_copy(update={'name':rows[0].name})
    values=map_players(r.model_copy(update={'players':tuple(rows)}),catalog())
    assert values[0]['mapping_status']==values[1]['mapping_status']=='ambiguous_duplicate_identity'
    assert values[0]['espn_id'] is None and values[1]['espn_id'] is None
    raw=r.model_dump(); raw['players'][0].update(espn_name_alias='Some Alias')
    with pytest.raises(ValidationError): RankingImport.model_validate(raw)
    raw=r.model_dump();raw['publication_status']='publisher_date_only'
    with pytest.raises(ValidationError): RankingImport.model_validate(raw)


def test_retrospective_snapshot_requires_explicit_policy_and_provenance():
    e=evidence()
    future={**snapshot(),'observed_at':(NOW+timedelta(days=1)).isoformat(),
            'available_at':(NOW+timedelta(days=1)).isoformat()}
    assert star_preview(e,future,StarSettings(),allow_first_snapshot=True)['bonus'] is None
    future.update(selection_mode='first_snapshot_backfill',retrospective=True,
                  first_snapshot_at=future['available_at'])
    assert star_preview(e,future,StarSettings())['bonus'] is None
    result=star_preview(e,future,StarSettings(),allow_first_snapshot=True)
    assert result['bonus']>0 and 'Retrospective' in result['reason']
    old=e.model_copy(update={'season':'2025-2026'})
    assert star_preview(old,future,StarSettings(),allow_first_snapshot=True)['bonus']>0
    assert star_preview(old,future,StarSettings())['bonus'] is None


def test_v6_requires_explicit_policy_and_v5_stays_strict():
    c=TuningConfig.model_validate_json((ROOT/'config/ranking/entertainment-stars-backfill-v6.json').read_text())
    assert c.star_snapshot_policy=='first_snapshot_backfill'
    old=TuningConfig.model_validate_json((ROOT/'config/ranking/entertainment-stars-v5.json').read_text())
    assert old.star_snapshot_policy is None
    with pytest.raises(ValidationError): TuningConfig.model_validate({**old.model_dump(),'star_snapshot_policy':'first_snapshot_backfill'})
    with pytest.raises(ValidationError): TuningConfig.model_validate({**c.model_dump(),'star_snapshot_policy':None})
