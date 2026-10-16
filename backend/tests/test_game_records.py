"""Source-shaped record claims, not reconstructed team histories."""
import copy
from datetime import date, datetime, timezone

import pytest

from morning_fixtures import summary, scoreboard
from nba_time_machine.sports import espn
from nba_time_machine.ranking.game_records import game_record_context
from nba_time_machine.workbench.context import RecordSettings, record_preview

DAY = date(2025, 11, 10)
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def payloads(event="123456789"):
    p = summary(event=event)
    p['header']['season'] = {'year':2026, 'type':2}
    comp = p['header']['competitions'][0]
    comp['date'] = '2025-11-11T02:00:00Z'
    for row, record, won in zip(comp['competitors'], ('7-4', '3-7'), (True, False)):
        row['record'] = [{'type':'total', 'summary':record, 'displayValue':record}]
        row['winner'] = won
    s = scoreboard(p)
    event = s['events'][0]
    event['date'] = comp['date']
    event['season'] = {'year':2026,'type':2}
    event['competitions'][0]['type'] = {'id':'1'}
    for row in event['competitions'][0]['competitors']:
        row['records'] = copy.deepcopy(row['record'])
    return p, s


def evidence_with_records(event="123456789"):
    p, s = payloads(event)
    return espn.summary(p, espn.scoreboard(s, DAY)[0], NOW)


def test_game_totals_are_retained_and_exactly_one_result_is_removed():
    e = evidence_with_records()
    assert e.pbp_usable and e.box_usable and e.records is not None
    assert not e.record_errors
    c = game_record_context(e)
    assert c['status']=='available'
    assert (c['home']['wins'],c['home']['losses'])==(6,4)
    assert (c['away']['wins'],c['away']['losses'])==(3,6)
    assert c['home']['removed_result']=='win' and c['away']['removed_result']=='loss'
    assert c['home']['conference_rank'] is None
    assert c['source_method']=='game_records' and c['standings']==[]


@pytest.mark.parametrize('fault',['missing','duplicate','mismatch','negative','winner','cup','preseason','ambiguous_basis','full_season_record'])
def test_bad_records_cannot_destroy_pbp_or_boxes_or_invent_importance(fault):
    p,s = payloads()
    rows = p['header']['competitions'][0]['competitors']
    if fault=='missing': rows[0].pop('record')
    if fault=='duplicate': rows[0]['record'] *= 2
    if fault=='mismatch': rows[0]['record'][0].update(summary='8-4',displayValue='8-4')
    if fault=='negative': rows[0]['record'][0].update(summary='-1-4',displayValue='-1-4')
    if fault=='winner': rows[0]['winner']=False
    if fault=='cup': s['events'][0]['competitions'][0]['type']['id']='39'
    if fault=='preseason': p['header']['season']['type']=1
    if fault=='ambiguous_basis': s['events'][0]['competitions'][0].pop('type')
    if fault=='full_season_record':
        for row in [rows[0],s['events'][0]['competitions'][0]['competitors'][0]]:
            for key in ('record','records'):
                if key in row: row[key][0].update(summary='41-41',displayValue='41-41')
    e=espn.summary(p,espn.scoreboard(s,DAY)[0],NOW)
    assert e.pbp_usable and e.box_usable
    c=game_record_context(e)
    assert c['status']!='available'
    assert record_preview(c, RecordSettings())['bonus'] is None


def test_stored_claim_revalidation_and_actual_strength_are_separate_from_standings():
    e=evidence_with_records()
    c=game_record_context(e)
    assert record_preview(c,RecordSettings())['bonus']==0  # One weak team.
    from nba_time_machine.sports.morning_models import MatchupRecords,SeasonRecord
    stronger = SeasonRecord(wins=8,losses=2)
    strong_e=e.model_copy(update={'records':MatchupRecords(home_after=stronger,away_after=stronger),
        'ref':e.ref.model_copy(update={'home_record':stronger,'away_record':stronger})})
    strong=record_preview(game_record_context(strong_e),RecordSettings())
    assert strong['bonus'] > 0
    assert 'leaders_magnitude' not in strong['calculation'] and 'race_magnitude' not in strong['calculation']
    inconsistent=e.model_copy(update={'records':MatchupRecords(home_after=stronger,away_after=e.records.away_after)})
    assert game_record_context(inconsistent)['status']=='missing'
