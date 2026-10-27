"""Validated, normalized completed-season evidence for the next season's prior."""
from datetime import datetime, timezone
import re

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from nba_time_machine.sports.morning_models import TEAM_NAMES, abbreviation, stamp

FACT_TYPE = 'team_strength.season_foundation.v1'
SOURCE_ID = 'espn-nba-games'


def previous_season(day):
    year = day.year if day.month >= 7 else day.year - 1
    return f'{year-1}-{year}'


def urls(season):
    year = int(season[-4:])
    return (f'https://site.api.espn.com/apis/v2/sports/basketball/nba/standings?season={year}&seasontype=2',
            f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={year}06&limit=100')


class PriorTeam(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    team: str
    external_id: str = Field(pattern=r'^\d+$')
    wins: int = Field(ge=0, le=82)
    losses: int = Field(ge=0, le=82)
    achievement: str = Field(pattern=r'^(champion|finalist|none)$')

    @model_validator(mode='after')
    def valid(self):
        if self.team not in TEAM_NAMES or self.wins + self.losses != 82:
            raise ValueError('incomplete_prior_team_record')
        return self


class SeasonFoundation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    season: str = Field(pattern=r'^202[4-6]-202[5-7]$')
    season_end: AwareDatetime
    finals_event_id: str = Field(pattern=r'^\d+$')
    teams: list[PriorTeam] = Field(min_length=30, max_length=30)

    @model_validator(mode='after')
    def valid(self):
        first, last = map(int, self.season.split('-'))
        if (last != first+1 or self.season_end.year != last
                or not datetime(last, 6, 1, tzinfo=timezone.utc) <= self.season_end < datetime(last, 7, 1, tzinfo=timezone.utc)
                or {t.team for t in self.teams} != set(TEAM_NAMES)
                or len({t.external_id for t in self.teams}) != 30
                or sum(t.wins for t in self.teams) != 1230
                or sum(t.losses for t in self.teams) != 1230
                or sum(t.achievement == 'champion' for t in self.teams) != 1
                or sum(t.achievement == 'finalist' for t in self.teams) != 1):
            raise ValueError('inconsistent_completed_season')
        return self


def parse_foundation(standings, finals, season, observed_at):
    """82-game records + an explicitly completed four-win NBA Finals series.

    No title is inferred from seeding, a regular-season leader, or prose summaries.
    """
    year = int(season[-4:])
    if (standings.get('abbreviation') != 'NBA' or standings.get('season', {}).get('year') != year
            or len(standings.get('children', [])) != 2):
        raise ValueError('wrong_prior_season')
    end = stamp(standings['season']['endDate'])
    if observed_at <= end:
        raise ValueError('prior_season_not_finished')
    teams = []
    for conference in standings['children']:
        entries = conference.get('standings', {}).get('entries', [])
        if len(entries) != 15:
            raise ValueError('incomplete_prior_standings')
        for entry in entries:
            team = entry['team']
            stats = {}
            for stat in entry['stats']:
                if stat.get('name') in ('wins', 'losses'):
                    if stat['name'] in stats:
                        raise ValueError('ambiguous_prior_record')
                    stats[stat['name']] = stat.get('value')
            def count(name):
                value = stats[name]
                if type(value) not in (int, float) or not 0 <= value <= 82 or value != int(value):
                    raise ValueError('invalid_prior_record')
                return int(value)
            abbr = abbreviation(team['abbreviation'])
            if team.get('displayName') != TEAM_NAMES[abbr]:
                raise ValueError('prior_team_identity_mismatch')
            teams.append(PriorTeam(team=abbr, external_id=str(team['id']), wins=count('wins'),
                                   losses=count('losses'), achievement='none'))
    by_id = {t.external_id: t for t in teams}
    completions = []
    if finals.get('leagues', [{}])[0].get('abbreviation') != 'NBA':
        raise ValueError('wrong_finals_league')
    events = finals.get('events')
    if not isinstance(events, list) or len(events) > 30:
        raise ValueError('invalid_finals_coverage')
    for event in events:
        # Structured type, explicit Finals round, final state, complete series,
        # four series wins, winner flag and final score must all agree.
        if event.get('season', {}).get('year') != year or event['season'].get('type') != 3:
            raise ValueError('wrong_finals_season')
        for comp in event.get('competitions', []):
            series = comp.get('series', {})
            if not series.get('completed'):
                continue
            if (series.get('completed') is not True or series.get('type') != 'playoff'
                    or series.get('totalCompetitions') != 7
                    or not any(re.fullmatch(r'NBA Finals - Game [1-7]', n.get('headline', '')) for n in comp.get('notes', []))
                    or event.get('status', {}).get('type', {}).get('completed') is not True
                    or not datetime(year, 6, 1, tzinfo=timezone.utc) <= stamp(event['date']) < end):
                raise ValueError('unverified_finals_completion')
            records = series.get('competitors', [])
            players = comp.get('competitors', [])
            if (len(records) != 2 or len(players) != 2 or len({str(r['id']) for r in records}) != 2
                    or {str(r['id']) for r in records} != {str(r['id']) for r in players}
                    or any(type(r.get('wins')) is not int or not 0 <= r['wins'] <= 4 for r in records)
                    or sum(r['wins'] == 4 for r in records) != 1):
                raise ValueError('invalid_finals_series')
            champion = str(next(r['id'] for r in records if r['wins'] == 4))
            finalist = str(next(r['id'] for r in records if r['wins'] != 4))
            winner = next(p for p in players if str(p['id']) == champion)
            loser = next(p for p in players if str(p['id']) == finalist)
            if (champion not in by_id or finalist not in by_id or winner.get('winner') is not True
                    or loser.get('winner') is not False or not str(winner.get('score','')).isdigit()
                    or not str(loser.get('score','')).isdigit() or int(winner['score']) <= int(loser['score'])):
                raise ValueError('finals_winner_mismatch')
            completions.append((str(event['id']), champion, finalist))
    if len(completions) != 1:
        raise ValueError('missing_or_ambiguous_champion')
    event_id, champion, finalist = completions[0]
    by_id[champion].achievement = 'champion'
    by_id[finalist].achievement = 'finalist'
    return SeasonFoundation(season=season, season_end=end, finals_event_id=event_id,
                            teams=sorted(teams, key=lambda t: t.team))
