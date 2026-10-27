"""Explicit once-per-season collection through canonical captures and temporal facts."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

import httpx
from sqlalchemy import select, text

from nba_time_machine.db import CollectionRunRecord, SeasonRecord, SourceOutcomeRecord, SourceRecord, TemporalFactRecord
from nba_time_machine.ingestion.contracts import RawCapture
from nba_time_machine.ingestion.runtime import _save_capture
from nba_time_machine.sports.morning import PublicNBAClient
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.sports.season_foundation import FACT_TYPE, SOURCE_ID, SeasonFoundation, parse_foundation, previous_season, urls

COLLECTOR = 'season-foundation-v1'


async def ensure_foundation(factory, day, *, force=False):
    """Called only by explicit collection. Failure does not prevent game ingestion."""
    season, now = previous_season(day), datetime.now(timezone.utc)
    if int(season[-4:]) not in (2025, 2026):
        return {'status': 'unsupported_season'}
    run_id = None
    client = None
    try:
        async with factory() as lock:
            if not await lock.scalar(text('SELECT pg_try_advisory_xact_lock(734387)')):
                return {'status': 'busy'}
            source = await lock.get(SourceRecord, SOURCE_ID)
            policy = source_policy(source, 'espn', manual=True)
            prior_season = await lock.scalar(select(SeasonRecord).where(SeasonRecord.league == 'NBA', SeasonRecord.label == season))
            if prior_season is not None and not force:
                latest = await lock.scalar(select(TemporalFactRecord).where(
                    TemporalFactRecord.season_id == prior_season.id, TemporalFactRecord.fact_type == FACT_TYPE,
                    TemporalFactRecord.source_id == SOURCE_ID).order_by(
                        TemporalFactRecord.observed_at.desc(), TemporalFactRecord.available_at.desc(), TemporalFactRecord.id.desc()).limit(1))
                if latest is not None:
                    try:
                        value = SeasonFoundation.model_validate_json(json.dumps(latest.value))
                        if (value.season == season and latest.observed_at <= now and latest.available_at <= now
                                and latest.valid_from <= now and (latest.valid_to is None or latest.valid_to > now)):
                            return {'status': 'stored', 'season': season}
                    except ValueError:
                        pass
            recent = await lock.scalar(select(CollectionRunRecord.id).where(
                CollectionRunRecord.collector_version == COLLECTOR,
                CollectionRunRecord.run_metadata['season'].astext == season,
                CollectionRunRecord.started_at > now - timedelta(days=1)).limit(1))
            if recent is not None and not force:
                return {'status': 'cooldown', 'season': season}
            run_id = uuid4()
            async with factory.begin() as session:
                session.add(CollectionRunRecord(id=run_id, started_at=now, collector_version=COLLECTOR,
                    run_metadata={'season': season, 'state': 'running'}))
            async with httpx.AsyncClient() as http:
                client = PublicNBAClient(http, max_requests=2)
                standings_url, finals_url = urls(season)
                standings = json.loads(await client.fetch('espn', standings_url, COLLECTOR))
                finals = json.loads(await client.fetch('espn', finals_url, COLLECTOR))
            captured = datetime.now(timezone.utc)
            value = parse_foundation(standings, finals, season, captured)
            body = value.model_dump_json()
            async with factory.begin() as session:
                source = await session.scalar(select(SourceRecord).where(SourceRecord.id == SOURCE_ID).with_for_update())
                if source_policy(source, 'espn', manual=True) != policy:
                    raise ValueError('source_policy_changed')
                prior_season = await session.scalar(select(SeasonRecord).where(SeasonRecord.league == 'NBA', SeasonRecord.label == season))
                if prior_season is None:
                    prior_season = SeasonRecord(league='NBA', label=season)
                    session.add(prior_season)
                    await session.flush()
                capture = RawCapture(source_id=SOURCE_ID, external_id='season-foundation:' + season,
                    discovered_at=captured, captured_at=captured, content_type='application/json',
                    text=body, content_hash=hashlib.sha256(body.encode()).hexdigest())
                written = await _save_capture(session, source, run_id, capture)
                if written:
                    session.add(TemporalFactRecord(subject_type='season', season_id=prior_season.id,
                        source_id=SOURCE_ID, fact_type=FACT_TYPE, value=value.model_dump(mode='json'),
                        observed_at=captured, available_at=captured, valid_from=captured,
                        fact_metadata={'collector_version': COLLECTOR, 'source_urls': list(urls(season)),
                                       'retrospective': True, 'actual_finish_time_unknown': True}))
                result = {'status': 'collected', 'season': season, 'requests': client.requests, 'captures_written': int(written)}
                run = await session.get(CollectionRunRecord, run_id)
                run.finished_at = captured
                run.run_metadata = result
                session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=SOURCE_ID,
                    status='ok' if written else 'idle', items_seen=30, captures_written=int(written),
                    finished_at=captured, outcome_metadata=result))
                return result
    except Exception:
        # Only fixed diagnostics; never leak provider bodies or connection details.
        if run_id is not None:
            async with factory.begin() as session:
                result = {'status': 'unavailable', 'season': season, 'requests': client.requests if client else 0}
                run = await session.get(CollectionRunRecord, run_id)
                run.finished_at = datetime.now(timezone.utc)
                run.run_metadata = result
                session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=SOURCE_ID,
                    status='parse_error', items_seen=0, captures_written=0, finished_at=run.finished_at,
                    error_code='season_foundation_unavailable', outcome_metadata=result))
        return {'status': 'unavailable', 'season': season}
