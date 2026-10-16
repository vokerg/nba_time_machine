"""Experimental reputation × actual participation, independent of game production."""
from math import sqrt
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StarSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    top5_value: float = Field(default=1., ge=0, le=1)
    top20_value: float = Field(default=.65, ge=0, le=1)
    top50_value: float = Field(default=.3, ge=0, le=1)
    top100_value: float = Field(default=.05, ge=0, le=1)
    top5_end: int = Field(default=5, ge=1, le=97)
    top20_end: int = Field(default=20, ge=2, le=98)
    top50_end: int = Field(default=50, ge=3, le=99)
    full_minutes: float = Field(default=30., gt=0, le=60)
    minutes_exponent: float = Field(default=1., gt=0, le=4)
    second_weight: float = Field(default=.4, ge=0, le=1)
    third_weight: float = Field(default=.15, ge=0, le=1)
    team_normalizer: float = Field(default=1.55, gt=0, le=3)
    both_teams_weight: float = Field(default=.6, ge=0, le=1)
    max_bonus: float = Field(default=1.5, ge=0, le=10)

    @model_validator(mode='after')
    def valid(self):
        if not self.top5_end < self.top20_end < self.top50_end < 100:
            raise ValueError('rank band boundaries must increase')
        if not self.top5_value >= self.top20_value >= self.top50_value >= self.top100_value:
            raise ValueError('rank values must decrease')
        if self.third_weight > self.second_weight:
            raise ValueError('additional stars must have diminishing weights')
        return self


def rank_value(rank, s):
    if rank <= s.top5_end:
        return s.top5_value
    knots = [(s.top5_end, s.top5_value), (s.top20_end, s.top20_value),
             (s.top50_end, s.top50_value), (100, s.top100_value)]
    for (lo, a), (hi, b) in zip(knots, knots[1:]):
        if rank <= hi:
            return a + (b - a) * (rank - lo) / (hi - lo)
    raise ValueError('rank out of range')


def star_preview(evidence, snapshot, settings):
    s = settings
    result = {'measurement_version': 'star-power-v1', 'status': 'unavailable', 'metric': None,
              'bonus': None, 'snapshot': snapshot, 'teams': [], 'settings': s.model_dump(),
              'reason': 'No approved ranking snapshot genuinely known before tipoff.',
              'unranked_note': 'Absent from this ranking does not mean low quality; injury exclusions are possible.'}
    if evidence is None or evidence.provider != 'espn' or evidence.status != 'final':
        result['reason'] = 'Final ESPN player evidence is required.'
        return result
    ranking = {r['espn_id']: r for r in (snapshot or {}).get('players', []) if r['mapping_status'] == 'matched'}
    unresolved = [r for r in (snapshot or {}).get('players', []) if r['mapping_status'] != 'matched']
    result['unresolved_identities'] = unresolved
    ids = [p.external_id for p in evidence.players]
    duplicate = len(ids) != len(set(ids))
    for team in (evidence.home, evidence.away):
        rows = [p for p in evidence.players if p.team_id == team.external_id]
        errors = []
        if not rows: errors.append('missing_team_box')
        if duplicate: errors.append('duplicate_player_ids')
        errors.extend(evidence.box_team_errors.get(team.external_id, ()))
        if 'invalid_box_schema' in evidence.box_errors or 'wrong_player_team' in evidence.box_errors:
            errors.append('invalid_box_identity_or_schema')
        # Independently establish each team's participation and total minutes.
        period_minutes = 48 + max(0, len(team.periods) - 4) * 5
        total_minutes = sum(p.minutes or 0 for p in rows if p.did_not_play is False)
        if not 5 * period_minutes - len(rows) <= total_minutes <= 5 * period_minutes + len(rows):
            errors.append('incomplete_team_minutes')
        players = []
        for p in rows:
            unknown = (p.did_not_play is None or (p.did_not_play is False and p.minutes is None)
                       or (p.did_not_play is True and ((p.minutes or 0) > 0 or bool(p.statistics)))
                       or (p.minutes or 0) > period_minutes)
            if unknown: errors.append('unknown_or_conflicting_participation')
            r = ranking.get(p.external_id)
            if r:
                status = ('unknown' if unknown else 'dnp' if p.did_not_play else
                          'played' if p.minutes > 0 else 'zero_minutes')
                factor = None if unknown else 0. if status != 'played' else min(1., p.minutes / s.full_minutes) ** s.minutes_exponent
                value = rank_value(r['rank'], s)
                players.append({'espn_id': p.external_id, 'name': p.name, 'rank': r['rank'],
                    'minutes': p.minutes, 'minutes_precision': p.minutes_precision,
                    'participation': status, 'rank_value': value, 'minutes_factor': factor,
                    'raw_contribution': None if factor is None else value * factor,
                    'slot_weight': 0., 'contribution': 0.})
        # Established rank chooses slots; DNP/zero/unknown never consumes a slot.
        active = sorted((p for p in players if p['participation'] == 'played'), key=lambda p: p['rank'])[:3]
        for p, weight in zip(active, (1., s.second_weight, s.third_weight)):
            p.update(slot_weight=weight, contribution=p['raw_contribution'] * weight)
        total = sum(p['contribution'] for p in active)
        result['teams'].append({'team': team.abbreviation, 'coverage': 'incomplete' if errors else 'complete',
            'errors': sorted(set(errors)), 'players': sorted(players, key=lambda p: p['rank']),
            'observed_team_minutes': total_minutes, 'expected_team_minutes': 5 * period_minutes,
            'raw_total': total, 'normalized': None if errors else min(1., total / s.team_normalizer)})
    if not snapshot or snapshot.get('status') != 'available':
        result['reason'] = (snapshot or {}).get('reason', result['reason'])
        return result
    if unresolved or any(t['coverage'] != 'complete' for t in result['teams']):
        result['reason'] = 'Unresolved ranking identities or incomplete team participation; no missing data extrapolation.'
        return result
    h, a = [t['normalized'] for t in result['teams']]
    metric = (1 - s.both_teams_weight) * max(h, a) + s.both_teams_weight * sqrt(h * a)
    result.update(status='available', reason='Top three participating ranked players per team; reputation is independent of game statistics.',
                  metric=metric, bonus=round(s.max_bonus * metric, 4))
    return result
