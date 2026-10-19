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
    GameObservationRecord, SourceRecord, SportsExternalIdentityRecord,
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

    async def _latest_observation(self, game_id, as_of):
        return await SqlAlchemyRankingEvidenceRepository(self.session).game_observation_as_of(game_id, as_of)

    async def _observations(self, game_id, source_id, as_of):
        o = GameObservationRecord
        return (await self.session.scalars(select(o).where(
            o.game_id == game_id, o.source_id == source_id,
            o.observed_at <= as_of, o.available_at <= as_of,
        ).order_by(o.observed_at.desc(), o.available_at.desc()).limit(2))).all()

    async def _facts(self, game_id, source_id, as_of, *, valid_from):
        f = TemporalFactRecord
        return (await self.session.scalars(select(f).where(
            f.game_id == game_id, f.fact_type == "provider_game_evidence",
            f.source_id == source_id, f.observed_at <= as_of, f.available_at <= as_of,
            *((f.subject_type == "game", f.valid_from <= as_of) if valid_from else ()),
        ).order_by(f.observed_at.desc(), f.available_at.desc()).limit(2))).all()

    async def _source(self, source_id):
        return await self.session.get(SourceRecord, source_id)

    async def _mapping(self, provider, external_id):
        return await self.session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == provider,
            SportsExternalIdentityRecord.entity_type == "game",
            SportsExternalIdentityRecord.external_id == external_id,
        ))

    async def derive_many(self, game_ids, *, as_of):
        """Batch only database reads; reuse all ordinary derivation/integrity rules."""
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if not game_ids:
            return {}
        batch = _BatchMorningRankingPipeline(self.session)
        await batch.load(game_ids, as_of)
        return {gid: await batch.derive(gid, as_of=as_of) for gid in game_ids}

    async def derive(self, game_id: UUID, *, as_of: datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        # The latest game observation masks older final states, across providers.
        observation = await self._latest_observation(game_id, as_of)
        if observation is None or observation.status != "final":
            return None
        result = await self._derive_observation(observation, as_of=as_of)
        if result is not None or observation.source_id != SOURCE_IDS["cbs"]:
            return result
        # CBS may have been fetched solely because ESPN's independent box
        # family was incomplete. Try only ESPN's latest revision, never an older
        # clean revision within that provider, and require current state agreement.
        primary = await self._observations(game_id, SOURCE_IDS["espn"], as_of)
        if not primary or (len(primary) == 2 and
                (primary[0].observed_at, primary[0].available_at) ==
                (primary[1].observed_at, primary[1].available_at)):
            return None
        candidate = primary[0]
        if (candidate.status != observation.status
                or candidate.scheduled_tip_at != observation.scheduled_tip_at
                or candidate.home_score != observation.home_score
                or candidate.away_score != observation.away_score):
            return None
        result = await self._derive_observation(candidate, as_of=as_of)
        if result is None:
            return None
        # Equal final scores alone do not establish equal OT/quarter history.
        # The backup's current evidence must agree on those period totals too.
        backups = await self._facts(game_id, observation.source_id, as_of, valid_from=False)
        if not backups or (len(backups) == 2 and
                (backups[0].observed_at, backups[0].available_at) ==
                (backups[1].observed_at, backups[1].available_at)):
            return None
        backup = backups[0]
        if (backup.observed_at != observation.observed_at
                or backup.available_at != observation.available_at
                or backup.valid_from > as_of
                or (backup.valid_to is not None and backup.valid_to <= as_of)):
            return None
        try:
            current = Evidence.model_validate({**backup.value, "observed_at": backup.observed_at})
            primary = Evidence.model_validate({**result[0].value, "observed_at": result[0].observed_at})
        except (ValidationError, ValueError, TypeError):
            return None
        if (current.home.periods != primary.home.periods or current.away.periods != primary.away.periods
                or current.game_type != primary.game_type or current.season != primary.season):
            return None
        return result

    async def _derive_observation(self, observation, *, as_of):
        game_id = observation.game_id
        rows = await self._facts(game_id, observation.source_id, as_of, valid_from=True)
        if not rows or (len(rows) == 2 and
                (rows[0].observed_at, rows[0].available_at) == (rows[1].observed_at, rows[1].available_at)):
            return None
        fact = rows[0]
        if fact.valid_to is not None and fact.valid_to <= as_of:
            return None  # No resurrection of an expired latest revision.
        try:
            evidence = Evidence.model_validate({**fact.value, "observed_at": fact.observed_at})
            source = await self._source(fact.source_id)
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
        mapped = await self._mapping(evidence.provider, evidence.external_id)
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


class _BatchMorningRankingPipeline(MorningRankingPipeline):
    """One cutoff and one bounded candidate set, discarded after derive_many.

    Window each provider independently so CBS fallback still sees the latest
    two ESPN revisions. Keep ties for the existing ambiguity checks.
    """

    async def _latest_two(self, model, game_ids, as_of, *criteria):
        from sqlalchemy import func
        ranked = select(model.id.label("id"), func.row_number().over(
            partition_by=(model.game_id, model.source_id),
            order_by=(model.observed_at.desc(), model.available_at.desc(), model.id.desc()),
        ).label("position")).where(
            model.game_id.in_(game_ids), model.observed_at <= as_of,
            model.available_at <= as_of, *criteria,
        ).subquery()
        rows = (await self.session.scalars(select(model).join(ranked, model.id == ranked.c.id)
            .where(ranked.c.position <= 2)
            .order_by(model.observed_at.desc(), model.available_at.desc(), model.id.desc()))).all()
        grouped = {}
        for row in rows:
            grouped.setdefault((row.game_id, row.source_id), []).append(row)
        return grouped

    async def load(self, game_ids, as_of):
        from nba_time_machine.db import GameRecord, SeasonRecord
        self.observations = await self._latest_two(GameObservationRecord, game_ids, as_of)
        f = TemporalFactRecord
        self.facts = await self._latest_two(f, game_ids, as_of, f.fact_type == "provider_game_evidence")
        self.valid_facts = await self._latest_two(f, game_ids, as_of,
            f.fact_type == "provider_game_evidence", f.subject_type == "game", f.valid_from <= as_of)
        source_ids = {source for _, source in self.observations} | {source for _, source in self.facts}
        self.sources = {row.id: row for row in (await self.session.scalars(
            select(SourceRecord).where(SourceRecord.id.in_(source_ids)))).all()}
        self.nba_games = set((await self.session.scalars(select(GameRecord.id)
            .join(SeasonRecord, GameRecord.season_id == SeasonRecord.id)
            .where(GameRecord.id.in_(game_ids), SeasonRecord.league == "NBA"))).all())
        # Match asserted IDs independently of the candidate game mapping. A wrong
        # canonical mapping must fail verification rather than disappear from it.
        external_ids = {row.value.get("external_id") for rows in self.valid_facts.values()
                        for row in rows if isinstance(row.value, dict)
                        and isinstance(row.value.get("external_id"), str)}
        self.mappings = {(row.provider_key, row.external_id): row.game_id for row in
            (await self.session.scalars(select(SportsExternalIdentityRecord).where(
                SportsExternalIdentityRecord.entity_type == "game",
                SportsExternalIdentityRecord.external_id.in_(external_ids)))).all()}

    async def _latest_observation(self, game_id, as_of):
        if game_id not in self.nba_games:
            return None
        rows = [row for (gid, _), values in self.observations.items() if gid == game_id for row in values]
        rows.sort(key=lambda row: (row.observed_at, row.available_at, row.id), reverse=True)
        if not rows or (len(rows) > 1 and (rows[0].observed_at, rows[0].available_at) ==
                       (rows[1].observed_at, rows[1].available_at)):
            return None
        source = self.sources.get(rows[0].source_id)
        return rows[0] if source is not None and source.verification_status == "verified" else None

    async def _observations(self, game_id, source_id, as_of):
        return self.observations.get((game_id, source_id), [])

    async def _facts(self, game_id, source_id, as_of, *, valid_from):
        return (self.valid_facts if valid_from else self.facts).get((game_id, source_id), [])

    async def _source(self, source_id):
        return self.sources.get(source_id)

    async def _mapping(self, provider, external_id):
        return self.mappings.get((provider, external_id))
