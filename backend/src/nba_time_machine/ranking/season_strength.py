"""A diminishing previous-season foundation; independent of favorites and outcomes."""
from datetime import datetime
import json

from sqlalchemy import select, func

from nba_time_machine.db import SeasonRecord, SportsExternalIdentityRecord, TemporalFactRecord, TeamRecord
from nba_time_machine.sports.morning_models import TEAM_NAMES
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.sports.season_foundation import FACT_TYPE, SOURCE_ID, SeasonFoundation, previous_season

PRIOR_GAMES = 20
VERSION = 'season-strength-v1'


def prior_rate(team):
    # Mild league-average shrinkage, then an explicit postseason reputation floor.
    regular = (team.wins + 5) / 92
    return max(regular, {'champion': .75, 'finalist': .68, 'none': 0}[team.achievement])


class SeasonStrengthReader:
    def __init__(self, batch, cutoff):
        self.batch, self.cutoff = batch, cutoff
        self.rows, self.mappings = {}, {}

    async def load(self):
        try:
            source_policy(self.batch.sources.get(SOURCE_ID), 'espn', manual=True)
        except ValueError:
            return
        seasons = {previous_season(datetime(int(label[:4]), 10, 1).date()) for _, label in self.batch.game_rows.values() if len(label) == 9 and label[:4].isdigit() and label[5:].isdigit()}
        f = TemporalFactRecord
        ranked = select(f.id.label('id'), func.row_number().over(partition_by=f.season_id,
            order_by=(f.observed_at.desc(), f.available_at.desc(), f.id.desc())).label('position')).where(
                f.subject_type == 'season', f.fact_type == FACT_TYPE, f.source_id == SOURCE_ID,
                f.observed_at <= self.cutoff, f.available_at <= self.cutoff).subquery()
        rows = (await self.batch.session.execute(select(SeasonRecord.label, f).join(SeasonRecord, SeasonRecord.id == f.season_id)
            .join(ranked, ranked.c.id == f.id).where(ranked.c.position <= 2, SeasonRecord.league == 'NBA',
                SeasonRecord.label.in_(seasons)).order_by(f.observed_at.desc(), f.available_at.desc(), f.id.desc()))).all()
        for label, row in rows:
            self.rows.setdefault(label, []).append(row)
        m = SportsExternalIdentityRecord
        self.mappings = {r.external_id: (r.team_id, name) for r, name in (await self.batch.session.execute(
            select(m, TeamRecord.name).join(TeamRecord, TeamRecord.id == m.team_id)
            .where(m.provider_key == 'espn', m.entity_type == 'team'))).all()}

    def apply(self, context, game_id, tip, *, strict=False):
        if context['status'] != 'available' or game_id not in self.batch.game_rows or tip is None:
            return context
        game, season = self.batch.game_rows[game_id]
        previous = f'{int(season[:4])-1}-{int(season[:4])}'
        rows = self.rows.get(previous, [])
        if not rows or len(rows) > 1 and (rows[0].observed_at, rows[0].available_at) == (rows[1].observed_at, rows[1].available_at):
            return context
        row = rows[0]
        if (row.valid_from > self.cutoff or row.valid_to is not None and row.valid_to <= self.cutoff
                or strict and max(row.observed_at, row.available_at) >= tip):
            return context
        try:
            foundation = SeasonFoundation.model_validate_json(json.dumps(row.value))
            if foundation.season != previous or foundation.season_end >= tip:
                return context
            teams = {t.team: t for t in foundation.teams}
            enriched = dict(context)
            for side, canonical in (('home', game.home_team_id), ('away', game.away_team_id)):
                current = context[side]
                prior = teams[current['team']]
                if self.mappings.get(prior.external_id) != (canonical, TEAM_NAMES[current['team']]):
                    return context
                enriched[side] = {**current, 'prior': {**prior.model_dump(), 'season': previous,
                    'win_rate': prior_rate(prior), 'equivalent_games': PRIOR_GAMES}}
            enriched['prior_provenance'] = {'source_ref': VERSION + ':' + str(row.id),
                'observed_at': row.observed_at, 'available_at': row.available_at,
                'season': previous, 'known_pre_tip': max(row.observed_at, row.available_at) < tip}
            return enriched
        except (ValueError, KeyError, TypeError):
            return context
