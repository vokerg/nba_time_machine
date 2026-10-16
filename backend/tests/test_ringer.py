"""Synthetic Top 100 HTML; publisher rankings/prose are never committed."""
from datetime import datetime, timezone
import pytest
from nba_time_machine.ingestion.ringer import parse_ranking


def page(count=100):
    return '<ol>' + ''.join(f'<li><h2><a href="/nba-ranked/top-100/synthetic-player-{i}">Synthetic Player {i}</a></h2></li>' for i in range(1,count+1)) + '</ol>'


def test_complete_ordered_snapshot_and_stable_content_version():
    now = datetime(2026,10,16,tzinfo=timezone.utc)
    p = parse_ranking(page(), now)
    assert len(p.players)==100 and p.players[-1].rank==100
    assert p.players[0].source_player_id=='synthetic-player-1'
    assert p.season=='2026-2027' and p.published_date is None
    assert p.ranking_version == parse_ranking(page().replace('<li>','<li class="new-style">'),now).ranking_version
    assert p.ranking_version != parse_ranking(page().replace('Synthetic Player 1<','Changed Player<'),now).ranking_version


@pytest.mark.parametrize('body',[page(99),page(101),page()+page(),'<h1>Verify you are human</h1>',page().replace('<ol>','<ol start="2">'),page().replace('synthetic-player-2"','synthetic-player-1"')])
def test_layout_challenges_incomplete_and_duplicate_rankings_rejected(body):
    with pytest.raises(ValueError): parse_ranking(body, datetime.now(timezone.utc))


def test_espn_identity_shapes_and_team_aliases():
    from nba_time_machine.sports.player_identities import teams, roster
    from nba_time_machine.sports.morning_models import TEAM_NAMES
    payload={'sports':[{'leagues':[{'teams':[{'team':{'id':str(i),'abbreviation':'NY' if abbr=='NYK' else abbr}} for i,abbr in enumerate(TEAM_NAMES,1)]}]}]}
    assert set(a for _,a in teams(payload))==set(TEAM_NAMES)
    r=roster({'athletes':[{'id':'123','displayName':'Synthetic Athlete'}]},'2','BOS')
    assert r.players[0].espn_id=='123'
    with pytest.raises(ValueError): roster({'team':{'id':'9'},'athletes':[]},'2','BOS')
    with pytest.raises(ValueError): roster({'athletes':[{'id':'123','displayName':'A'},{'id':'123','displayName':'B'}]},'2','BOS')


def test_labeled_publication_date_is_separate_from_availability():
    now=datetime(2026,10,16,tzinfo=timezone.utc)
    p=parse_ranking('<p>Updated October 14, 2026.</p>'+page(),now)
    assert p.published_date.isoformat()=='2026-10-14'
    assert p.publication_status=='publisher_date_only'
    assert '2026-10-14' in p.ranking_version
    with pytest.raises(ValueError): parse_ranking('<p>Updated October 14, 2026. Updated October 15, 2026.</p>'+page(),now)
