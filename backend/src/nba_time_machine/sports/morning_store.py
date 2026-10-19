"""Persist morning evidence through existing captures, identities and temporal facts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from nba_time_machine.db import CollectionRunRecord, SourceOutcomeRecord, SourceRecord, TemporalFactRecord
from nba_time_machine.ingestion.contracts import RawCapture
from nba_time_machine.ingestion.runtime import _save_capture
from nba_time_machine.sports.contracts import NormalizedGameObservation, NormalizedProviderTeam
from nba_time_machine.sports.errors import SportsProviderResponseError
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.repository import StructuredSportsStore


def source_policy(source, provider: str, *, manual: bool) -> tuple:
    expected = {"espn": "https://site.api.espn.com", "cbs": "https://www.cbssports.com"}
    if (source is None or source.id != SOURCE_IDS[provider] or source.adapter != provider + "_nba"
            or source.kind != "structured" or source.locator.rstrip("/") != expected[provider]
            or source.verification_status != "verified" or source.requires_auth
            or source.retention_policy != "normalized_full" or (not source.enabled and not manual)):
        raise ValueError("morning_source_policy_not_ready")
    # Serialize nested settings so a mutation cannot change both snapshots in place.
    return (source.enabled, source.verification_status, source.adapter, source.kind, source.locator,
            source.requires_auth, source.retention_policy, json.dumps(source.adapter_settings, sort_keys=True))


class MorningStore:
    def __init__(self, factory, *, manual=False):
        self.factory, self.manual = factory, manual

    async def collect(self, collector, day, *, game_id=None):
        # Same lock as existing sports ingestion: cross-provider identity matching is serialized.
        async with self.factory() as lock:
            if not await lock.scalar(text("SELECT pg_try_advisory_xact_lock(734387)")):
                raise ValueError("sports_collection_already_running")
            policies = {}
            async with self.factory() as session:
                for provider, source_id in SOURCE_IDS.items():
                    source = await session.get(SourceRecord, source_id)
                    policies[provider] = source_policy(source, provider, manual=self.manual)
            # A run exists before the first request, so interruption leaves visible work.
            run_id = uuid4()
            async with self.factory.begin() as session:
                session.add(CollectionRunRecord(id=run_id, started_at=datetime.now(timezone.utc),
                    collector_version="nba-morning-v1", run_metadata={"day": day.isoformat(), "state": "running"}))
            try:
                report = await collector.collect(day, game_id=game_id)
                report.run_id = str(run_id)
                for provider, source_id in SOURCE_IDS.items():
                    await lock.execute(text("SELECT 1"))
                    await self._provider(report, provider, source_id, policies[provider], run_id)
                async with self.factory.begin() as session:
                    run = await session.get(CollectionRunRecord, run_id)
                    run.finished_at = datetime.now(timezone.utc)
                    run.run_metadata = report.diagnostics()
                return report
            except BaseException:
                async with self.factory.begin() as session:
                    run = await session.get(CollectionRunRecord, run_id)
                    run.finished_at = datetime.now(timezone.utc)
                    run.run_metadata = {"day": day.isoformat(), "state": "interrupted"}
                raise

    async def _provider(self, report, provider, source_id, policy, run_id):
        values = [e for g in report.games for e in g.evidence if e.provider == provider]
        attempts = [a for a in report.attempts if a.provider == provider]
        written, rejected, changed_policy = 0, 0, False
        for evidence in values:
            # Each game commits independently; a collision cannot discard unrelated games.
            try:
                async with self.factory.begin() as session:
                    source = await session.scalar(select(SourceRecord).where(
                        SourceRecord.id == source_id).with_for_update())
                    try:
                        approved = source_policy(source, provider, manual=self.manual) == policy
                    except ValueError:
                        approved = False
                    if not approved:
                        changed_policy = True
                        break
                    value = evidence.retained_value()
                    body = json.dumps(value, sort_keys=True, separators=(",", ":"))
                    capture = RawCapture(source_id=source_id, external_id="game:" + evidence.external_id,
                        discovered_at=evidence.observed_at, captured_at=evidence.observed_at,
                        content_type="application/json", text=body,
                        content_hash=hashlib.sha256(body.encode()).hexdigest())
                    # Do not let a capture hash suppress an identity-integrity check.
                    normalized = NormalizedGameObservation(external_event_id=evidence.external_id,
                        season_label=evidence.season,
                        home_team=NormalizedProviderTeam(evidence.home.external_id, evidence.home.name),
                        away_team=NormalizedProviderTeam(evidence.away.external_id, evidence.away.name),
                        status=evidence.status if evidence.status in ("final", "scheduled") else "in_progress",
                        scheduled_tip_at=evidence.ref.scheduled_at,
                        home_score=None if evidence.status == "scheduled" else evidence.home.score,
                        away_score=None if evidence.status == "scheduled" else evidence.away.score,
                        metadata={"provider": provider, "game_type": evidence.game_type,
                                  "pbp_usable": evidence.pbp_usable, "box_usable": evidence.box_usable})
                    store = StructuredSportsStore(source_id=source_id, provider_key=provider, reconcile_existing=True)
                    # Resolve identities before dedup, but append an observation only for a new revision.
                    game = await store.resolve_game_identity(session, normalized)
                    if await _save_capture(session, source, run_id, capture):
                        await store.store_game_observation(session, normalized, observed_at=evidence.observed_at)
                        session.add(TemporalFactRecord(subject_type="game", game_id=game.id,
                            fact_type="provider_game_evidence", value=value, source_id=source_id,
                            valid_from=evidence.observed_at, observed_at=evidence.observed_at,
                            available_at=evidence.observed_at,
                            fact_metadata={"provider_key": provider, "external_event_id": evidence.external_id,
                                "pbp_usable": evidence.pbp_usable, "box_usable": evidence.box_usable,
                                "player_ids_are_provider_namespaced": True, "trusted_final_at": None}))
                        written += 1
            except (SportsProviderResponseError, ValueError):
                rejected += 1
                report.persistence_errors.append(provider + ":identity_or_policy_rejected")
            except SQLAlchemyError:
                rejected += 1
                report.persistence_errors.append(provider + ":persist_failed")
        report.captures_written += written
        failures = [a for a in attempts if a.status not in ("ok", "redirected")]
        source_errors = [err for err in report.errors if err.startswith(provider + "_")]
        partial = any((e.entering_records is None or bool(e.record_errors)) if e.status == "scheduled"
                      else (not e.pbp_usable or not e.box_usable) for e in values)
        if changed_policy:
            status = "skipped_config"
            report.persistence_errors.append(provider + ":source_policy_changed")
        elif rejected or (values and (partial or failures or source_errors)):
            status = "partial"
        elif not values and failures:
            status = "rate_limited" if any(a.http_status == 429 for a in failures) else "blocked" if any(a.http_status in (401, 403) for a in failures) else "network_error"
        elif not values and source_errors:
            status = "parse_error"
        else:
            status = "ok" if written else "idle"
        async with self.factory.begin() as session:
            session.add(SourceOutcomeRecord(collection_run_id=run_id, source_id=source_id, status=status,
                items_seen=len(values), captures_written=written, finished_at=datetime.now(timezone.utc),
                outcome_metadata={"attempts": [asdict(a) for a in attempts], "rejected": rejected,
                    "errors": source_errors,
                    "games": len(values), "pbp_usable": sum(e.pbp_usable for e in values),
                    "box_usable": sum(e.box_usable for e in values), "partial": partial}))
