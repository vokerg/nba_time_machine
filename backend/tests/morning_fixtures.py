"""Generated synthetic source-shaped fixtures, not retained publisher content."""
import copy
import html
import json

DAY = "2026-10-13"
EVENT = "123456789"
TIP = "2026-10-14T02:00:00Z"


def summary(event=EVENT, home_id="13", away_id="9"):
    teams = [dict(id=home_id, homeAway="home", team=dict(id=home_id, abbreviation="LAL"),
                  score="4", linescores=[dict(displayValue="1") for _ in range(4)]),
             dict(id=away_id, homeAway="away", team=dict(id=away_id, abbreviation="GS"),
                  score="3", linescores=[dict(displayValue=str(i)) for i in (1, 1, 1, 0)])]
    plays = []
    def play(period, clock, h, a, kind="1", scoring=False, pts=0):
        plays.append(dict(id=event + str(len(plays) + 1), sequenceNumber=str(len(plays) + 1),
            type=dict(id=kind), period=dict(number=period), clock=dict(displayValue=clock),
            homeScore=h, awayScore=a, scoringPlay=scoring, scoreValue=pts,
            participants=[], wallclock="2026-10-14T04:00:00Z"))
    play(1, "12:00", 0, 0)
    for p in range(1, 5):
        play(p, "11:00", p, min(p - 1, 3), scoring=True, pts=1)
        if p < 4:
            play(p, "10:00", p, p, scoring=True, pts=1)
        play(p, "0.0", p, min(p, 3), kind="412")
    play(4, "0.0", 4, 3, kind="402")
    names = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]
    boxes = []
    for team_id, player_id, pts in [(away_id, "1001", 3), (home_id, "2001", 4)]:
        boxes.append(dict(team=dict(id=team_id), statistics=[dict(names=names, athletes=[
            dict(athlete=dict(id=player_id, displayName="Synthetic Player " + player_id),
                 starter=True, didNotPlay=False,
                 stats=["48", str(pts), "0-0", "0-0", f"{pts}-{pts}", "1", "0", "0", "0", "0", "0", "1", "0", "+1"])
        ])]))
    return dict(header=dict(id=event, season=dict(year=2027, type=1), competitions=[dict(
        id=event, date=TIP, competitors=teams, status=dict(type=dict(completed=True)))]),
        plays=plays, boxscore=dict(players=boxes), meta=dict(lastPlayWallClock="2026-10-14T04:00:00Z"))


def scoreboard(payload=None):
    source = copy.deepcopy(payload or summary())
    header = source["header"]
    return dict(events=[dict(id=header["id"], date=TIP, status=dict(type=dict(completed=True)),
                             competitions=header["competitions"])])


def cbs_html(home_id="345", away_id="341", abbr="NBA_20261013_GS@LAL"):
    data = dict(id=50000001, gameAbbr=abbr, scheduled_epoch=1791943200,
                hometeam=dict(id=home_id, abbr="LAL"), awayteam=dict(id=away_id, abbr="GS"),
                homeTeamScore=4, awayTeamScore=3, status="FINAL", seasonYear=2026,
                seasonType="pre", game_status=dict(
                    homescore=dict(quarter={str(i): "1" for i in range(1, 5)}),
                    awayscore=dict(quarter={str(i): str(min(i, 3) - min(i - 1, 3)) for i in range(1, 5)})))
    content = "<script>var current_game_scoreboard = JSON.parse('" + html.escape(json.dumps(data), quote=True) + "'.replace(/&quot;/g,'\"'));</script>"
    for period in range(1, 5):
        content += '<table><tr>' + ''.join('<th>' + v + '</th>' for v in ["Time", "Team", "", "Play", "Score"]) + '</tr>'
        content += f'<tr><td>10:00</td><td></td><td></td><td>Synthetic action</td><td>{min(period,3)}-{period}</td></tr>'
        content += '<tr><td>0:00</td><td></td><td></td><td>End of period</td><td></td></tr></table>'
    labels = ["Starters", "PTS", "REB", "AST", "FG", "3PT", "FT", "PF", "MIN", "STL", "BLK", "TO", "OREB", "DREB", "+/-", "FPTS"]
    for side, pid, points in [("away", "3001", 3), ("home", "4001", 4)]:
        content += f'<div id="player-stats-{side}"><table><tr>' + ''.join(f'<td>{v}</td>' for v in labels) + '</tr>'
        row = [f'<a href="/nba/players/{pid}/synthetic-player/">Synthetic Player</a>', str(points), "1", "0", "0/0", "0/0", f"{points}/{points}", "0", "48", "0", "0", "0", "0", "1", "+1", "0"]
        content += '<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr></table></div>'
    return content
