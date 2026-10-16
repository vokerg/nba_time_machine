"""Bounded ESPN current-roster identity evidence; no statistics or availability inference."""
import json
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from pydantic import Field, model_validator
from sqlalchemy import select, text

from nba_time_machine.db import CollectionRunRecord, SourceOutcomeRecord, SourceRecord, TemporalFactRecord
from nba_time_machine.ingestion.contracts import RawCapture
from nba_time_machine.ingestion.runtime import _save_capture
from nba_time_machine.ranking.player_rankings import digest
from nba_time_machine.sports.morning import PublicNBAClient, SOURCE_IDS
from nba_time_machine.sports.morning_models import Model, TEAM_NAMES, abbreviation
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.sports.repository import StructuredSportsStore
from nba_time_machine.sports.contracts import NormalizedProviderTeam

FACT_TYPE = 'provider_player_identities.espn-v1'
COLLECTOR_VERSION = 'espn-roster-identities-v3'
BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams'


class Identity(Model):
    espn_id: str = Field(pattern=r'^[0-9]{1,20}$')
    name: str = Field(min_length=1, max_length=120)
    team: str


class Roster(Model):
    team: str
    team_id: str = Field(pattern=r'^[0-9]{1,10}$')
    players: tuple[Identity, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode='after')
    def valid(self):
        if (self.team not in TEAM_NAMES or any(p.team != self.team for p in self.players)
                or len({p.espn_id for p in self.players}) != len(self.players)):
            raise ValueError('invalid_roster_identity')
        return self


def teams(payload):
    values = payload['sports'][0]['leagues'][0]['teams']
    rows = [(v['team']['id'], abbreviation(v['team']['abbreviation'])) for v in values]
    if (len(rows) != 30 or {a for _, a in rows} != set(TEAM_NAMES)
            or len({i for i, _ in rows}) != 30 or any(not i.isdigit() for i, _ in rows)):
        raise ValueError('invalid_nba_teams')
    return rows


def roster(payload, team_id, team):
    if payload.get('team', {}).get('id', team_id) != team_id:
        raise ValueError('wrong_roster_team')
    return Roster(team=team, team_id=team_id, players=tuple(Identity(
        espn_id=p['id'], name=p.get('displayName') or p['fullName'], team=team) for p in sorted(payload['athletes'], key=lambda p: p['id'])))


async def collect_identities(factory, *, transport=None):
    async with factory() as session:
        policy = source_policy(await session.get(SourceRecord, SOURCE_IDS['espn']), 'espn', manual=True)
    run_id, started = uuid4(), datetime.now(timezone.utc)
    async with factory.begin() as session:
        if not await session.scalar(text('SELECT pg_try_advisory_xact_lock(734390)')):
            return {'state': 'already_running'}
        last = await session.scalar(select(CollectionRunRecord.started_at).where(
            CollectionRunRecord.collector_version == COLLECTOR_VERSION).order_by(
            CollectionRunRecord.started_at.desc()).limit(1))
        if last and started < last + timedelta(days=14):
            return {'state': 'not_due'}
        session.add(CollectionRunRecord(id=run_id, started_at=started,
            collector_version=COLLECTOR_VERSION, run_metadata={'state': 'running'}))
    written, seen, errors = 0, 0, []
    try:
        async with httpx.AsyncClient(transport=transport) as http:
            client = PublicNBAClient(http, max_requests=31)
            rows = teams(json.loads(await client.fetch('espn', BASE, 'identity_teams')))
            for team_id, team in rows:
                try:
                    url = BASE + '/' + team_id + '/roster'
                    value = roster(json.loads(await client.fetch('espn', url, 'identity_roster')), team_id, team).model_dump(mode='json')
                    observed = datetime.now(timezone.utc)
                    async with factory.begin() as session:
                        await session.execute(text('SELECT pg_advisory_xact_lock(734387)'))
                        source = await session.get(SourceRecord, SOURCE_IDS['espn'], with_for_update=True)
                        if source_policy(source, 'espn', manual=True) != policy:
                            raise ValueError('source_policy_changed')
                        target = await StructuredSportsStore(source_id=source.id, provider_key='espn',
                            reconcile_existing=True)._ensure_team(session, NormalizedProviderTeam(team_id, TEAM_NAMES[team]))
                        capture = RawCapture(source_id=source.id, external_id='roster:' + team_id,
                            canonical_url=url, discovered_at=observed, captured_at=observed,
                            content_type='application/json', text=json.dumps(value), content_hash=digest(value))
                        if await _save_capture(session, source, run_id, capture):
                            session.add(TemporalFactRecord(subject_type='team', team_id=target.id,
                                fact_type=FACT_TYPE, source_id=source.id, value=value,
                                valid_from=observed, observed_at=observed, available_at=observed,
                                fact_metadata={'provider': 'espn', 'source_url': url,
                                    'identity_only': True, 'not_game_participation': True}))
                            written += 1
                    seen += len(value['players'])
                except Exception:
                    errors.append('roster_unavailable:' + team)
    except asyncio.CancelledError:
        errors.append('roster_interrupted')
        raise
    except Exception as error:
        code = str(error)
        errors.append('roster_discovery_failed:' + (code if code in {
            'invalid_nba_teams', 'http_403', 'http_401', 'http_429', 'timeout',
            'network_or_encoding_error', 'response_too_large'} else 'invalid_response'))
    finally:
        async with factory.begin() as session:
            run = await session.get(CollectionRunRecord, run_id)
            run.finished_at = datetime.now(timezone.utc)
            run.run_metadata = {'identities': seen, 'captures_written': written, 'errors': errors}
            session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=SOURCE_IDS['espn'],
                status='partial' if errors else 'ok', items_seen=seen, captures_written=written,
                finished_at=run.finished_at, outcome_metadata=run.run_metadata))
    return {'identities': seen, 'captures_written': written, 'errors': errors}
