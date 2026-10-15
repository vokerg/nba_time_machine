"""Stored evidence -> versioned feature bundle -> existing hidden score archive.

No fetches, inferred actual final time, pregame inputs, or public serialization.
Caller owns the transaction; the sports advisory lock serializes writes.
"""
from dataclasses import asdict
from datetime import date, datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text

from nba_time_machine.db import (
    SourceRecord, SportsExternalIdentityRecord,
    TemporalFactRecord,
)
from nba_time_machine.ranking.evidence import SqlAlchemyRankingEvidenceRepository
from nba_time_machine.ranking.morning_features import FEATURE_VERSION, trajectory_features
from nba_time_machine.ranking.repository import SqlAlchemyRankingStore
from nba_time_machine.ranking.scoring import FeatureObservation, score_postgame
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.morning_models import Evidence
from nba_time_machine.sports.morning_store import source_policy

PREFIX = FEATURE_VERSION + ":"
BUNDLE_TYPE = "ranking.features." + FEATURE_VERSION


class MorningRankingPipeline:
    def __init__(self, session):
        self.session = session

    async def derive(self, game_id: UUID, *, as_of: datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        # The latest game observation masks older final states, across providers.
        observation = await SqlAlchemyRankingEvidenceRepository(self.session).game_observation_as_of(game_id, as_of)
        if observation is None or observation.status != "final":
            return None
        rows = (await self.session.scalars(select(TemporalFactRecord).where(
            TemporalFactRecord.subject_type == "game",
            TemporalFactRecord.game_id == game_id,
            TemporalFactRecord.fact_type == "provider_game_evidence",
            TemporalFactRecord.source_id == observation.source_id,
            TemporalFactRecord.available_at <= as_of,
            TemporalFactRecord.observed_at <= as_of,
            TemporalFactRecord.valid_from <= as_of,
        ).order_by(TemporalFactRecord.observed_at.desc(),
                   TemporalFactRecord.available_at.desc()).limit(2))).all()
        if not rows or (len(rows) == 2 and
                (rows[0].observed_at, rows[0].available_at) == (rows[1].observed_at, rows[1].available_at)):
            return None
        fact = rows[0]
        if fact.valid_to is not None and fact.valid_to <= as_of:
            return None  # No resurrection of an expired latest revision.
        try:
            evidence = Evidence.model_validate({**fact.value, "observed_at": fact.observed_at})
            source = await self.session.get(SourceRecord, fact.source_id)
            source_policy(source, evidence.provider, manual=True)
        except (ValidationError, ValueError, TypeError):
            return None
        if (fact.source_id != SOURCE_IDS[evidence.provider]
                or fact.observed_at != observation.observed_at
                or fact.available_at != observation.available_at
                or evidence.ref.scheduled_at != observation.scheduled_tip_at
                or evidence.ref.scheduled_at is None
                or evidence.home.score != observation.home_score
                or evidence.away.score != observation.away_score):
            return None
        # Verify the canonical game mapping, not just IDs asserted in JSON.
        mapped = await self.session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == evidence.provider,
            SportsExternalIdentityRecord.entity_type == "game",
            SportsExternalIdentityRecord.external_id == evidence.external_id,
        ))
        if mapped != game_id or evidence.ref.external_id != evidence.external_id:
            return None
        boundary = max(fact.observed_at, fact.available_at)
        if boundary <= evidence.ref.scheduled_at:
            return None
        metrics = trajectory_features(evidence)
        if metrics is None:
            return None
        features = {signal: FeatureObservation(
            value=value, source_ref=PREFIX + str(fact.id),
            observed_at=fact.observed_at, available_at=fact.available_at,
        ) for signal, value in metrics.normalized().items()}
        # final_at here is a conservative scoring eligibility boundary, never
        # written to game_observations.final_at or claimed as the actual finish.
        score = score_postgame(game_id, features, final_at=boundary, as_of=as_of)
        return fact, metrics, score

    async def process(self, game_id: UUID, *, as_of: datetime, write: bool = False,
                      slate_date: date | None = None) -> bool:
        if write:
            await self.session.execute(text("SELECT pg_advisory_xact_lock(734387)"))
            # Coordinate registry revocation with feature/archive writes too.
            await self.session.execute(select(SourceRecord).where(
                SourceRecord.id.in_(SOURCE_IDS.values())).order_by(SourceRecord.id).with_for_update())
        result = await self.derive(game_id, as_of=as_of)
        if result is None:
            return False
        fact, metrics, score = result
        if slate_date is not None and fact.value["ref"]["day"] != slate_date.isoformat():
            return False
        if write:
            existing = (await self.session.scalars(select(TemporalFactRecord).where(
                TemporalFactRecord.game_id == game_id,
                TemporalFactRecord.fact_type == BUNDLE_TYPE,
                TemporalFactRecord.fact_metadata["input_fact_id"].astext == str(fact.id),
            ))).all()
            value = {"metrics": asdict(metrics), "normalized": {
                signal.value: amount for signal, amount in metrics.normalized().items()}}
            if existing:
                if len(existing) != 1 or existing[0].value != value:
                    raise ValueError("derived feature revision collision")
            else:
                self.session.add(TemporalFactRecord(
                    subject_type="game", game_id=game_id, source_id=fact.source_id,
                    fact_type=BUNDLE_TYPE, value=value, valid_from=fact.valid_from,
                    available_at=fact.available_at, observed_at=fact.observed_at,
                    fact_metadata={"input_fact_id": str(fact.id),
                        "derivation_version": FEATURE_VERSION,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "finality_basis": "validated_final_observed",
                        "actual_final_at": None},
                ))
            await SqlAlchemyRankingStore(self.session).archive(score)
        return True
