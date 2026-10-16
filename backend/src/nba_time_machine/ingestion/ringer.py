"""Private owner-directed Top 100 check. One fixed URL, no access bypass or retries."""
import asyncio
from datetime import datetime, timedelta, timezone
import re
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy import text

from nba_time_machine.db import CollectionRunRecord, SourceOutcomeRecord, SourceRecord, TemporalFactRecord
from nba_time_machine.ranking.player_rankings import SOURCE_ID, SOURCE_URL, FACT_TYPE, RankingImport, RankedPlayer, digest
from nba_time_machine.ranking.player_ranking_store import approved, import_snapshot
from nba_time_machine.sports.cbs import Document, Element

INTERVAL = timedelta(days=14)
ACCESS_REFERENCE = 'owner-directed-private-hobby-2026-10-16-not-publisher-license'


def parse_ranking(body, observed):
    """Require a single complete ordered list; never rank arbitrary page links."""
    doc = Document(body)
    candidates = []
    for ol in doc.root.find('ol'):
        items = [c for c in ol.children if isinstance(c, Element) and c.tag == 'li']
        if len(items) != 100 or ol.attrs.get('start', '1') != '1':
            continue
        rows = []
        for index, item in enumerate(items, 1):
            headings = list(item.find('h2'))
            links = [a for a in item.find('a') if re.fullmatch(
                r'(?:https://www\.theringer\.com)?/nba-ranked/top-100/[a-z0-9-]+/?', a.attrs.get('href') or '')]
            urls = {a.attrs['href'].rstrip('/') for a in links}
            if len(headings) != 1 or len(urls) != 1:
                raise ValueError('ringer_player_card_changed')
            rows.append({'rank': index, 'name': headings[0].text(),
                         'source_player_id': next(iter(urls)).split('/')[-1]})
        candidates.append(rows)
    if len(candidates) != 1:
        raise ValueError('ringer_top100_structure_changed')
    rows = candidates[0]
    def visible(node):
        return '' if node.tag in ('script', 'style') else ' '.join(
            visible(c) if isinstance(c, Element) else c for c in node.children)
    dates = set(re.findall(r'\bUpdated\s+([A-Z][a-z]+ \d{1,2}, \d{4})\.', visible(doc.root)))
    if len(dates) > 1:
        raise ValueError('ringer_publication_date_ambiguous')
    published = datetime.strptime(next(iter(dates)), '%B %d, %Y').date() if dates else None
    # A labeled publisher date is separate from actual availability. No timestamp
    # is invented from HTTP headers or a date-only page label.
    year = observed.year if observed.month >= 8 else observed.year - 1
    return RankingImport.model_validate({
        'ranking_version': 'ringer-top100-' + (published.isoformat() + '-' if published else '') + digest({'players': rows})[:16],
        'season': f'{year}-{year+1}', 'publication_status': 'publisher_date_only' if published else 'unknown',
        'published_date': published, 'publication_reference': SOURCE_URL + ' · Updated label' if published else None,
        'permission_reference': ACCESS_REFERENCE, 'players': rows,
    })


async def configure_hobby_source(factory):
    """Explicit CLI setup only. Records owner direction, never a publisher grant."""
    async with factory.begin() as session:
        source = await session.get(SourceRecord, SOURCE_ID, with_for_update=True)
        if source is None:
            source = SourceRecord(id=SOURCE_ID, name='The Ringer Top 100 · private hobby',
                kind='structured', locator=SOURCE_URL, adapter='ringer_top100_hobby',
                verification_status='unverified', enabled=False, cadence_minutes=20160,
                requires_auth=False, retention_policy='normalized_full', adapter_settings={})
            session.add(source)
        # Preserve the persistent attempt cursor when configuring again.
        source.adapter = 'ringer_top100_hobby'
        source.locator = SOURCE_URL
        source.cadence_minutes = 20160
        source.retention_policy = 'normalized_full'
        source.adapter_settings = {**source.adapter_settings,
            'automated_access': True, 'auto_refresh': True,
            'access_basis': 'owner_directed_private_hobby',
            'permission_reference': ACCESS_REFERENCE,
            'publisher_permission': False, 'private_only': True,
            'terms_restriction_acknowledged': True}


async def refresh_if_due(factory, *, transport=None):
    now = datetime.now(timezone.utc)
    run_id = uuid4()
    # Commit reservation BEFORE HTTP, so crashes, failures and simultaneous
    # processes cannot cause another network attempt within fourteen days.
    async with factory.begin() as session:
        source = await session.get(SourceRecord, SOURCE_ID, with_for_update=True)
        if source is None or source.adapter != 'ringer_top100_hobby' or not source.adapter_settings.get('auto_refresh'):
            return {'state': 'not_configured'}
        settings = source.adapter_settings
        if (settings.get('access_basis') != 'owner_directed_private_hobby'
                or not settings.get('private_only') or not settings.get('automated_access')
                or source.locator != SOURCE_URL or source.retention_policy != 'normalized_full'
                or source.requires_auth or source.kind != 'structured'):
            return {'state': 'policy_not_ready'}
        last = source.runtime_cursor.get('attempted_at') if source.runtime_cursor else None
        if last and now < datetime.fromisoformat(last) + INTERVAL:
            return {'state': 'not_due', 'next_check_at': (datetime.fromisoformat(last) + INTERVAL).isoformat()}
        source.runtime_cursor = {'attempted_at': now.isoformat(), 'run_id': str(run_id)}
        session.add(CollectionRunRecord(id=run_id, started_at=now,
            collector_version='ringer-top100-fetch-v1', run_metadata={'state': 'running', 'private_hobby': True}))
    status, code, result = 'network_error', 'ringer_network_error', None
    try:
        async with asyncio.timeout(45):
            async with httpx.AsyncClient(transport=transport, follow_redirects=False) as http:
                async with http.stream('GET', SOURCE_URL, timeout=30,
                    headers={'User-Agent': 'NBATimeMachine-PrivateHobby/1.0 (14-day checks)'}) as response:
                    if response.status_code != 200:
                        status = 'rate_limited' if response.status_code == 429 else 'blocked'
                        raise ValueError('ringer_http_' + str(response.status_code))
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise ValueError('ringer_response_too_large')
                        chunks.append(chunk)
                    payload = parse_ranking(b''.join(chunks).decode('utf-8'), datetime.now(timezone.utc))
            async with factory.begin() as session:
                await session.execute(text('SELECT pg_advisory_xact_lock(734388)'))
                source = await session.get(SourceRecord, SOURCE_ID, with_for_update=True)
                if source.adapter_settings != settings:
                    raise ValueError('ringer_policy_changed')
                source.verification_status = 'verified'  # format/access check, not publisher permission
                await session.flush()
                result = await import_snapshot(session, payload, write=True, automated=True)
                status = 'ok' if result['validation_status'] == 'complete' else 'partial'
                code = 'ringer_snapshot_saved' if result['written'] else 'ringer_snapshot_unchanged'
    except asyncio.CancelledError:
        code = 'ringer_interrupted'
        raise
    except (ValueError, UnicodeError) as error:
        value = str(error)
        code = value if re.fullmatch(r'ringer_[a-z0-9_]+', value) else 'ringer_validation_failed'
        if status == 'network_error': status = 'parse_error'
    except (httpx.HTTPError, TimeoutError):
        pass
    except Exception:
        code = 'ringer_persistence_failed'
    finally:
        async with factory.begin() as session:
            run = await session.get(CollectionRunRecord, run_id)
            run.finished_at = datetime.now(timezone.utc)
            run.run_metadata = {'state': status, 'code': code, 'result': result}
            session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=SOURCE_ID,
                status=status, items_seen=100 if result else 0,
                captures_written=int(bool(result and result['written'])), finished_at=run.finished_at,
                outcome_metadata={'code': code, 'coverage': result['coverage'] if result else None}))
    return {'state': status, 'code': code, 'result': result}


async def source_status(session):
    source = await session.get(SourceRecord, SOURCE_ID)
    if source is None:
        return {'state': 'not_configured'}
    run = await session.scalar(select(CollectionRunRecord).join(SourceOutcomeRecord,
        SourceOutcomeRecord.collection_run_id == CollectionRunRecord.id).where(
        SourceOutcomeRecord.source_id == SOURCE_ID).order_by(CollectionRunRecord.started_at.desc()).limit(1))
    last = source.runtime_cursor.get('attempted_at') if source.runtime_cursor else None
    snapshot = await session.scalar(select(TemporalFactRecord).where(
        TemporalFactRecord.source_id == SOURCE_ID, TemporalFactRecord.fact_type == FACT_TYPE).order_by(
        TemporalFactRecord.observed_at.desc()).limit(1))
    attempt = await session.get(CollectionRunRecord, source.runtime_cursor.get('run_id')) if last else None
    latest = attempt.run_metadata if attempt else run.run_metadata if run else None
    state = 'ready' if snapshot and snapshot.value.get('validation_status') == 'complete' else 'identities_incomplete' if snapshot else 'awaiting_first_check'
    if latest and latest.get('state') not in (None, 'ok', 'partial'):
        state = 'checking' if latest['state'] == 'running' else 'fetch_failed'
    try:
        approved(source)
    except ValueError:
        state = 'policy_not_ready'
    return {'state': state, 'format_verification': source.verification_status, 'access_basis': source.adapter_settings.get('access_basis'),
            'publisher_permission': source.adapter_settings.get('publisher_permission', False),
            'last_attempt_at': last,
            'next_check_at': (datetime.fromisoformat(last) + INTERVAL).isoformat() if last else None,
            'latest_run': latest,
            'snapshot_coverage': snapshot.value.get('coverage') if snapshot else None,
            'snapshot_known_at': snapshot.available_at.isoformat() if snapshot else None}


async def complete_identities(factory, *, transport=None):
    """Reinterpret an already captured ranking without another publisher fetch."""
    async with factory() as session:
        source = await session.get(SourceRecord, SOURCE_ID)
        if source is None or source.adapter != 'ringer_top100_hobby' or not source.adapter_settings.get('auto_refresh'):
            return {'state': 'not_configured'}
        approved(source)
        fact = await session.scalar(select(TemporalFactRecord).where(
            TemporalFactRecord.source_id == SOURCE_ID, TemporalFactRecord.fact_type == FACT_TYPE).order_by(
            TemporalFactRecord.observed_at.desc()).limit(1))
        if fact is None or fact.value['validation_status'] == 'complete':
            return {'state': 'no_mapping_work'}
        data = fact.value
        original = {k: v for k, v in data.items() if k in RankingImport.model_fields}
        original['players'] = [{**{k: v for k, v in p.items() if k in RankedPlayer.model_fields},
                                'espn_id': p.get('requested_espn_id')} for p in data['players']]
        payload = RankingImport.model_validate(original)
    from nba_time_machine.sports.player_identities import collect_identities
    roster_result = await collect_identities(factory, transport=transport)
    async with factory.begin() as session:
        dry = await import_snapshot(session, payload, automated=True)
        if dry['revision_hash'] == fact.fact_metadata['revision_hash']:
            return {'state': 'unchanged', 'coverage': dry['coverage'], 'rosters': roster_result}
        result = await import_snapshot(session, payload, write=True, automated=True)
    return {'state': 'mapping_updated', 'result': result, 'rosters': roster_result}


async def automatic_checks(factory):
    while True:
        try:
            await refresh_if_due(factory)
            await complete_identities(factory)
        except Exception:
            pass  # persisted run stays inspectable; DB outage must not stop workbench
        await asyncio.sleep(3600)
