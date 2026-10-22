"""Known-before-tip roster star potential. No boxes, results or injury assumptions."""
from types import SimpleNamespace
from sqlalchemy import select, func

from nba_time_machine.db import SeasonRecord, SourceRecord, SportsExternalIdentityRecord, TemporalFactRecord, TeamRecord
from nba_time_machine.ranking.player_rankings import SOURCE_ID, FACT_TYPE
from nba_time_machine.ranking.player_ranking_store import approved, read_snapshot
from nba_time_machine.ranking.star_power import StarSettings, team_star_power, matchup_star_power
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.sports.player_identities import Roster, FACT_TYPE as ROSTER_TYPE


class PregameStarReader:
    def __init__(self, session, games, sources, cutoff, *, latest_tip):
        self.session, self.games, self.sources, self.cutoff = session, games, sources, cutoff
        self.ranking_rows, self.rosters, self.team_mappings = [], {}, {}
        self.ready = False
        self.latest_tip = latest_tip

    async def load(self):
        try:
            approved(self.sources.get(SOURCE_ID))
            source_policy(self.sources.get(SOURCE_IDS['espn']), 'espn', manual=True)
        except ValueError:
            return
        f = TemporalFactRecord
        self.ranking_rows = (await self.session.execute(select(SeasonRecord.label, f).join(
            SeasonRecord, SeasonRecord.id == f.season_id).where(f.source_id == SOURCE_ID,
            f.fact_type == FACT_TYPE, SeasonRecord.league == 'NBA',
            f.observed_at <= self.cutoff, f.available_at <= self.cutoff,
            f.observed_at < self.latest_tip, f.available_at < self.latest_tip)
            .order_by(f.observed_at.desc(), f.available_at.desc()).limit(513))).all()
        if len(self.ranking_rows) > 512:
            return
        # Two latest revisions per team suffice to retain ambiguity detection.
        # Select before validity/schema checks; never resurrect a clean old roster.
        latest = select(f.id.label('id'), func.row_number().over(partition_by=f.team_id,
            order_by=(f.observed_at.desc(), f.available_at.desc(), f.id.desc())).label('position')).where(
            f.fact_type == ROSTER_TYPE, f.source_id == SOURCE_IDS['espn'],
            f.observed_at <= self.cutoff, f.available_at <= self.cutoff,
            f.observed_at < self.latest_tip, f.available_at < self.latest_tip).subquery()
        for row in (await self.session.scalars(select(f).join(latest, latest.c.id == f.id)
                .where(latest.c.position <= 2))).all():
            self.rosters.setdefault(row.team_id, []).append(row)
        for rows in self.rosters.values():
            rows.sort(key=lambda r: (r.observed_at, r.available_at), reverse=True)
        m = SportsExternalIdentityRecord
        self.team_mappings = {row.external_id: (row.team_id, name) for row, name in (await self.session.execute(
            select(m, TeamRecord.name).join(TeamRecord, TeamRecord.id == m.team_id)
            .where(m.provider_key == 'espn', m.entity_type == 'team'))).all()}
        self.ready = True

    async def read(self, gid, tip):
        missing = {'snapshot': None, 'potential': None}
        if not self.ready or gid not in self.games or tip is None:
            return missing
        game, season = self.games[gid]
        snapshot = await read_snapshot(self.session, SimpleNamespace(season=season,
            ref=SimpleNamespace(scheduled_at=tip)), self.cutoff,
            known_rows=self.ranking_rows, known_source=self.sources[SOURCE_ID])
        result = {'snapshot': snapshot, 'potential': None}
        if snapshot['status'] != 'available':
            return result
        eligible = {}
        for tid, rows in self.rosters.items():
            rows = [r for r in rows if r.observed_at < tip and r.available_at < tip]
            if not rows:
                continue
            row = rows[0]
            if (len(rows) > 1 and (row.observed_at, row.available_at) == (rows[1].observed_at, rows[1].available_at)
                    or row.valid_from > self.cutoff or row.valid_from >= tip
                    or row.valid_to is not None and row.valid_to <= self.cutoff):
                continue
            try:
                roster = Roster.model_validate(row.value)
                from nba_time_machine.sports.morning_models import TEAM_NAMES
                if (row.subject_type != 'team' or not row.fact_metadata.get('identity_only')
                        or self.team_mappings.get(roster.team_id) != (tid, TEAM_NAMES[roster.team])):
                    continue
                eligible[tid] = (row, roster)
            except ValueError:
                continue
        wanted = (game.home_team_id, game.away_team_id)
        if any(tid not in eligible for tid in wanted):
            return result
        ids = [p.espn_id for _, roster in eligible.values() for p in roster.players]
        ranking = {p['espn_id']: p for p in snapshot['players']}
        settings, teams, evidence = StarSettings(), [], []
        for tid in wanted:
            fact, roster = eligible[tid]
            if any(ids.count(p.espn_id) != 1 for p in roster.players):
                return result
            ranked = [
                {'espn_id': p.espn_id, 'name': ranking[p.espn_id]['name'],
                 'rank': ranking[p.espn_id]['rank'], 'factor': 1.}
                for p in roster.players if p.espn_id in ranking
            ]
            players, total, normalized = team_star_power(ranked, settings)
            slots = {p['espn_id']: p for p in players}
            ranked_players = [
                {'name': p['name'], 'rank': p['rank'],
                 'slot_weight': slots.get(p['espn_id'], {}).get('slot_weight', 0.),
                 'contribution': slots.get(p['espn_id'], {}).get('contribution', 0.)}
                for p in sorted(ranked, key=lambda player: player['rank'])
            ]
            teams.append({'team': roster.team, 'normalized': normalized,
                          'ranked_players': ranked_players,
                          'unranked_players': sorted(p.name for p in roster.players if p.espn_id not in ranking),
                          'players': [{'name':p['name'], 'rank':p['rank'],
                                       'slot_weight':p['slot_weight'], 'contribution':p['contribution']}
                                      for p in players]})
            evidence.append({'source_ref': 'roster:' + str(fact.id),
                             'observed_at': fact.observed_at, 'available_at': fact.available_at})
        metric = matchup_star_power(teams[0]['normalized'], teams[1]['normalized'], settings)
        evidence.append({'source_ref': 'ranking:' + snapshot['fact_id'],
                         'observed_at': snapshot['observed_at'], 'available_at': snapshot['available_at']})
        result['potential'] = {'rating': round(10 * metric, 4), 'overall_points': round(settings.max_bonus * metric, 4),
            'teams': teams, 'evidence': evidence,
            'explanation': 'Ranked players on rosters known before tip-off. This measures roster star potential; injuries, lineups and playing time are unconfirmed.'}
        return result
