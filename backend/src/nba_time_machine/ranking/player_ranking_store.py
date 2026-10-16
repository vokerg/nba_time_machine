"""Manual ranking snapshots use canonical captures + season temporal facts only."""
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text

from nba_time_machine.db import (CollectionRunRecord, SeasonRecord, SourceOutcomeRecord,
                                SourceRecord, TemporalFactRecord)
from nba_time_machine.ingestion.contracts import RawCapture
from nba_time_machine.ingestion.runtime import _save_capture
from nba_time_machine.ranking.player_rankings import (SOURCE_ID, SOURCE_URL, FACT_TYPE,
                                                      RankingImport, digest, map_players)
from nba_time_machine.sports.morning_models import Evidence


def approved(source, permission=None):
    if (source is None or source.locator != SOURCE_URL or source.adapter != 'manual_player_rankings'
            or source.verification_status != 'verified' or source.requires_auth
            or source.retention_policy not in ('normalized_full', 'full')
            or not source.adapter_settings.get('permission_reference')
            or source.adapter_settings.get('automated_access', False)):
        raise ValueError('ranking_source_permission_or_retention_not_approved')
    if permission is not None and permission != source.adapter_settings['permission_reference']:
        raise ValueError('ranking_permission_reference_mismatch')


async def identity_catalog(session, as_of):
    facts = (await session.scalars(select(TemporalFactRecord).where(
        TemporalFactRecord.fact_type == 'provider_game_evidence',
        TemporalFactRecord.observed_at <= as_of, TemporalFactRecord.available_at <= as_of,
    ).order_by(TemporalFactRecord.observed_at.desc()).limit(5001))).all()
    if len(facts) > 5000:
        raise ValueError('identity_catalog_over_5000_fact_bound')
    rows = []
    for fact in facts:
        try:
            e = Evidence.model_validate({**fact.value, 'observed_at': fact.observed_at})
            if e.provider != 'espn': continue
            from nba_time_machine.sports.morning_store import source_policy
            source_policy(await session.get(SourceRecord, fact.source_id), 'espn', manual=True)
        except ValueError:
            continue
        for p in e.players:
            team = next((t.abbreviation for t in (e.home, e.away) if t.external_id == p.team_id), None)
            if team and p.external_id.isdigit():
                rows.append({'espn_id': p.external_id, 'name': p.name, 'team': team, 'fact_id': str(fact.id)})
    return rows


async def import_snapshot(session, payload: RankingImport, *, write=False):
    """Caller owns transaction; all writes atomic. Import never accepts timestamps."""
    now = datetime.now(timezone.utc)
    if payload.published_date and payload.published_date > now.date():
        raise ValueError('publication_date_is_in_future')
    if write:
        await session.execute(text('SELECT pg_advisory_xact_lock(734388)'))
    source = await session.scalar(select(SourceRecord).where(SourceRecord.id == SOURCE_ID).with_for_update()) if write else await session.get(SourceRecord, SOURCE_ID)
    approved(source, payload.permission_reference)
    players = map_players(payload, await identity_catalog(session, now))
    data = payload.model_dump(mode='json')
    data['players'] = players
    data['content_version'] = digest({**payload.model_dump(mode='json'), 'players': [p.model_dump(mode='json') for p in sorted(payload.players, key=lambda p: p.rank)]})
    data['mapping_version'] = 'espn-name-team-v1'
    data['coverage'] = {'expected': 100, 'ranked': len(players),
                        'matched': sum(p['mapping_status'] == 'matched' for p in players)}
    data['validation_status'] = 'complete' if data['coverage']['matched'] == 100 else 'unresolved_identities'
    # Mapping evidence expands over time; irrelevant repeated supporting facts do
    # not create a new source version. Preserve first mapping proof on duplicate.
    signature = digest({**data, 'players': [{k: v for k, v in p.items() if k != 'mapping_fact_ids'} for p in players]})
    report = {'written': False, 'coverage': data['coverage'], 'validation_status': data['validation_status'],
              'content_version': data['content_version'], 'revision_hash': signature}
    if not write:
        return report
    season = await session.scalar(select(SeasonRecord).where(SeasonRecord.league == 'NBA', SeasonRecord.label == payload.season))
    if season is None:
        season = SeasonRecord(league='NBA', label=payload.season)
        session.add(season)
        await session.flush()
    run = CollectionRunRecord(id=uuid4(), started_at=now, finished_at=now,
                              collector_version='manual-player-rankings-v1', run_metadata={'manual': True})
    session.add(run)
    await session.flush()
    capture = RawCapture(source_id=SOURCE_ID, external_id='top100:' + payload.season,
        canonical_url=SOURCE_URL, discovered_at=now, captured_at=now,
        content_type='application/json', text=json.dumps(data, sort_keys=True), content_hash=signature)
    written = await _save_capture(session, source, run.id, capture)
    if written:
        session.add(TemporalFactRecord(subject_type='season', season_id=season.id, source_id=SOURCE_ID,
            fact_type=FACT_TYPE, value=data, valid_from=now, observed_at=now, available_at=now,
            fact_metadata={'revision_hash': signature, 'source_url': SOURCE_URL,
                'publication_precision': payload.publication_status, 'manual': True}))
    session.add(SourceOutcomeRecord(collection_run_id=run.id, source_id=SOURCE_ID,
        status='partial' if data['validation_status'] != 'complete' else 'ok' if written else 'idle',
        items_seen=100, captures_written=int(written), finished_at=now,
        outcome_metadata={'coverage': data['coverage'], 'validation_status': data['validation_status']}))
    return {**report, 'written': written, 'run_id': str(run.id), 'observed_at': now.isoformat()}


async def read_snapshot(session, evidence, as_of):
    missing = {'status': 'unavailable', 'players': [], 'reason': 'No ranking snapshot genuinely observed before tipoff.'}
    if evidence is None or evidence.ref.scheduled_at is None:
        return missing
    try:
        approved(await session.get(SourceRecord, SOURCE_ID))
    except ValueError:
        return {**missing, 'reason': 'Ranking source permission/retention is not approved.'}
    tip = evidence.ref.scheduled_at
    rows = (await session.scalars(select(TemporalFactRecord).join(SeasonRecord,
        SeasonRecord.id == TemporalFactRecord.season_id).where(
        TemporalFactRecord.source_id == SOURCE_ID, TemporalFactRecord.fact_type == FACT_TYPE,
        SeasonRecord.label == evidence.season, SeasonRecord.league == 'NBA',
        TemporalFactRecord.observed_at < tip, TemporalFactRecord.available_at < tip,
        TemporalFactRecord.observed_at <= as_of, TemporalFactRecord.available_at <= as_of,
    ).order_by(TemporalFactRecord.observed_at.desc(), TemporalFactRecord.available_at.desc()).limit(2))).all()
    if not rows: return missing
    fact = rows[0]
    if (fact.valid_from > as_of or (fact.valid_to is not None and fact.valid_to <= as_of)
            or len(rows) > 1 and (rows[1].observed_at, rows[1].available_at) == (fact.observed_at, fact.available_at)):
        return {**missing, 'reason': 'Latest pre-tip ranking is invalid or ambiguous; older versions are not substituted.'}
    data = fact.value
    try:
        # Validate the normalized source contract again on reads.
        original = {k: v for k, v in data.items() if k in RankingImport.model_fields}
        original['players'] = [{k: v for k, v in p.items() if k in __import__('nba_time_machine.ranking.player_rankings', fromlist=['RankedPlayer']).RankedPlayer.model_fields} for p in data['players']]
        RankingImport.model_validate(original)
        if (len(data['players']) != 100 or len({p['espn_id'] for p in data['players'] if p['espn_id']}) != data['coverage']['matched']):
            raise ValueError('invalid mapping')
    except (ValueError, KeyError, TypeError):
        return {**missing, 'reason': 'Latest pre-tip ranking failed schema validation.'}
    return {**data, 'status': 'available' if data['validation_status'] == 'complete' else 'unavailable',
        'reason': 'Validated manual snapshot; availability is import time, not claimed publication date.',
        'fact_id': str(fact.id), 'observed_at': fact.observed_at.isoformat(),
        'captured_at': fact.observed_at.isoformat(), 'available_at': fact.available_at.isoformat()}
