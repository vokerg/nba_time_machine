"""Synthetic ESPN pre-tip totals and state disagreements."""
from datetime import datetime, timedelta
import copy
import pytest
import httpx

from test_game_records import payloads, DAY
from nba_time_machine.sports import espn
from nba_time_machine.sports.morning import MorningCollector, PublicNBAClient
from nba_time_machine.ranking.pregame_records import scheduled_record_context
from nba_time_machine.ranking.pregame import expectation, PregameExpectation


def scheduled_payloads(event='123456789'):
    p,s = payloads(event)
    p.pop('plays'); p.pop('boxscore'); p.pop('meta')
    comp = p['header']['competitions'][0]
    comp['type'] = {'id':'1'}
    comp['status'] = {'type':{'completed':False, 'state':'pre', 'name':'STATUS_SCHEDULED'}, 'period':0}
    for row in comp['competitors']:
        row.pop('winner'); row.pop('linescores'); row['score']='0'
    event = s['events'][0]
    event['status'] = copy.deepcopy(comp['status'])
    event['competitions'][0] = copy.deepcopy(comp)
    for row in event['competitions'][0]['competitors']:
        row['records'] = copy.deepcopy(row['record'])
    return p,s


def scheduled_evidence(event='123456789'):
    p,s=scheduled_payloads(event)
    tip=datetime.fromisoformat(p['header']['competitions'][0]['date'].replace('Z','+00:00'))
    return espn.summary(p,espn.scoreboard(s,DAY)[0],tip-timedelta(hours=2))


def test_pre_tip_totals_are_used_directly_with_shared_formula():
    e=scheduled_evidence()
    c=scheduled_record_context(e)
    assert c['status']=='available'
    assert (c['home']['wins'],c['home']['losses'])==(7,4)
    assert (c['away']['wins'],c['away']['losses'])==(3,7)
    v=expectation(c, source_ref='fixture', observed_at=e.observed_at, available_at=e.observed_at)
    assert PregameExpectation.model_validate(v).basis=='known-pre-tip'
    assert not e.pbp_usable and not e.box_usable and e.records is None


@pytest.mark.parametrize('fault', ['tip', 'live', 'period', 'points', 'winner', 'plays', 'rescheduled'])
def test_live_and_ambiguous_schedules_cannot_become_pregame_records(fault):
    p,s=scheduled_payloads()
    ref=espn.scoreboard(s,DAY)[0]
    observed=scheduled_evidence().observed_at
    comp=p['header']['competitions'][0]
    if fault=='tip': observed=ref.scheduled_at
    if fault=='live': comp['status']['type']['state']='in'
    if fault=='period': comp['status']['period']=1
    if fault=='points': comp['competitors'][0]['score']='1'
    if fault=='winner': comp['competitors'][0]['winner']=False
    if fault=='plays': p['plays']=[{'text':'untrusted'}]
    if fault=='rescheduled': comp['date']='2025-11-11T03:00:00Z'
    with pytest.raises(ValueError): espn.summary(p,ref,observed)


@pytest.mark.parametrize('fault', ['mismatch','cup','preseason','late_record'])
def test_bad_record_claims_do_not_invent_a_record_score(fault):
    p,s=scheduled_payloads()
    if fault=='mismatch': p['header']['competitions'][0]['competitors'][0]['record'][0]['summary']='8-4'
    if fault=='cup': s['events'][0]['competitions'][0]['type']={'id':'39'}
    if fault=='preseason':
        p['header']['season']['type']=1; s['events'][0]['season']['type']=1
    e=espn.summary(p,espn.scoreboard(s,DAY)[0],scheduled_evidence().observed_at)
    if fault=='late_record': e=e.model_copy(update={'observed_at':e.ref.scheduled_at})
    assert scheduled_record_context(e)['status']!='available'


@pytest.mark.asyncio
async def test_scheduled_collection_uses_existing_bounded_endpoints_without_cbs(monkeypatch):
    # Fix collection time before this synthetic scheduled tip.
    p,s=scheduled_payloads()
    from nba_time_machine.sports import morning
    observed=scheduled_evidence().observed_at
    class Clock:
        @staticmethod
        def now(tz): return observed
    monkeypatch.setattr(morning,'datetime',Clock)
    calls=[]
    def handler(req):
        calls.append(req)
        assert req.url.host=='site.api.espn.com'
        return httpx.Response(200,json=s if 'scoreboard' in req.url.path else p)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        report=await MorningCollector(PublicNBAClient(http,interval=0)).collect(DAY)
    assert len(calls)==2 and not report.errors
    assert report.games[0].evidence[0].entering_records is not None
