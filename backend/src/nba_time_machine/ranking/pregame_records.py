"""Read genuine pre-tip totals; latest revisions mask older claims before validation."""
from sqlalchemy import select, func, and_
from sqlalchemy.orm import aliased

from nba_time_machine.db import (
    GameObservationRecord, TemporalFactRecord, SportsExternalIdentityRecord, TeamRecord,
)
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.morning_models import Evidence, TEAM_NAMES
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.ranking.game_records import RECORD_WINDOWS
from nba_time_machine.ranking.pregame import expectation


def scheduled_record_context(evidence):
    e = evidence
    missing = {'status':'missing', 'home':None, 'away':None}
    window = RECORD_WINDOWS.get(e.season)
    if (e.provider != 'espn' or e.status != 'scheduled' or not e.ref.pregame
            or e.ref.final is not False or e.ref.scheduled_at is None or e.observed_at >= e.ref.scheduled_at
            or e.game_type != 'regular_season' or e.ref.season_type != 2
            or e.ref.competition_type in (None, '39') or window is None
            or not window[0] <= e.ref.day <= window[1] or e.record_errors or e.ref.record_errors
            or e.entering_records is None or e.records is not None or e.plays or e.players
            or e.home.score or e.away.score or e.home.periods or e.away.periods):
        return missing
    result = {'status':'available', 'basis':'known-pre-tip'}
    for side in ('home', 'away'):
        record = getattr(e.entering_records, side)
        if record != getattr(e.ref, side + '_record') or record.wins + record.losses > (e.ref.day-window[0]).days:
            return missing
        result[side] = {'team':getattr(e.ref, side), 'wins':record.wins, 'losses':record.losses,
                        'games_played':record.wins + record.losses}
    return result


async def read_pregame_records(batch, game_ids, cutoff):
    """One batched query, bounded to two historical observations per game.

    Select observations before joining facts, so a missing/corrupt newest fact
    cannot resurrect an older clean capture. Facts retain their actual timestamps.
    """
    try:
        source_policy(batch.sources.get(SOURCE_IDS['espn']), 'espn', manual=True)
    except ValueError:
        return {}, {}
    o, f = GameObservationRecord, TemporalFactRecord
    ranked = select(o.id.label('id'), func.row_number().over(partition_by=o.game_id,
        order_by=(o.observed_at.desc(), o.available_at.desc(), o.id.desc())).label('position')).where(
            o.game_id.in_(game_ids), o.source_id == SOURCE_IDS['espn'],
            o.observed_at <= cutoff, o.available_at <= cutoff,
            o.observed_at < o.scheduled_tip_at, o.available_at < o.scheduled_tip_at).subquery()
    hm, am, gm = (aliased(SportsExternalIdentityRecord) for _ in range(3))
    ht, at = aliased(TeamRecord), aliased(TeamRecord)
    rows = (await batch.session.execute(select(o, f, hm.team_id, am.team_id, ht.name, at.name, gm.game_id)
        .join(ranked, ranked.c.id == o.id)
        .outerjoin(f, and_(f.game_id == o.game_id, f.source_id == o.source_id,
            f.fact_type == 'provider_game_evidence', f.observed_at == o.observed_at,
            f.available_at == o.available_at))
        .outerjoin(gm, and_(gm.provider_key == 'espn', gm.entity_type == 'game',
            gm.external_id == f.value['external_id'].astext))
        .outerjoin(hm, and_(hm.provider_key == 'espn', hm.entity_type == 'team',
            hm.external_id == f.value['home']['external_id'].astext))
        .outerjoin(am, and_(am.provider_key == 'espn', am.entity_type == 'team',
            am.external_id == f.value['away']['external_id'].astext))
        .outerjoin(ht, ht.id == hm.team_id).outerjoin(at, at.id == am.team_id)
        .where(ranked.c.position <= 2)
        .order_by(o.observed_at.desc(), o.available_at.desc(), o.id.desc()))).all()
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0].game_id, []).append(row)
    ratings, records = {}, {}
    batch.record_contexts = {}
    for gid, values in grouped.items():
        o, f, home_id, away_id, home_name, away_name, mapped = values[0]
        if (gid not in batch.game_rows or f is None or len(values)>1 and
                (o.observed_at, o.available_at) == (values[1][0].observed_at, values[1][0].available_at)):
            continue
        latest = await batch._latest_observation(gid, cutoff)
        game, season = batch.game_rows[gid]
        if (latest is None or latest.scheduled_tip_at != o.scheduled_tip_at
                or latest.status in ('canceled', 'postponed', 'suspended')
                or o.status != 'scheduled' or o.home_score is not None or o.away_score is not None
                or o.actual_tip_at is not None or o.final_at is not None or mapped != gid
                or (home_id, away_id) != (game.home_team_id, game.away_team_id)
                or f.subject_type != 'game' or f.valid_from > cutoff or f.valid_from >= o.scheduled_tip_at
                or f.valid_to is not None and f.valid_to <= cutoff):
            continue
        try:
            e = Evidence.model_validate({**f.value, 'observed_at':f.observed_at})
            if (e.season != season or e.ref.external_id != e.external_id
                    or e.ref.scheduled_at != o.scheduled_tip_at
                    or (home_name, away_name) != (TEAM_NAMES[e.ref.home], TEAM_NAMES[e.ref.away])):
                continue
            context = scheduled_record_context(e)
        except (ValueError, TypeError, KeyError):
            continue
        if context['status'] != 'available':
            continue
        batch.record_contexts[str(gid)] = {'context': context, 'source_ref': 'pregame-records:' + str(f.id),
            'observed_at': f.observed_at, 'available_at': f.available_at}
        records[str(gid)] = {'basis':'known-pre-tip',
            'teams':[{key:context[side][key] for key in ('team','wins','losses')} for side in ('home','away')],
            'observed_at':f.observed_at, 'available_at':f.available_at}
        rating = expectation(context, source_ref='pregame-records:' + str(f.id),
                              observed_at=f.observed_at, available_at=f.available_at)
        if rating is not None:
            ratings[str(gid)] = rating
    return ratings, records
