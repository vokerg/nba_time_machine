"""Trusted, as-of game-level ranking feature extraction from temporal facts.

Only server-persisted observations and explicitly normalized game facts enter
scoring. This repository is internal: it does not authorize postgame disclosure.
Unknown, malformed, stale or future evidence is omitted, never guessed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db import (
    GameObservationRecord, GameRecord, SeasonRecord, SourceRecord, TemporalFactRecord,
)
from nba_time_machine.ranking.scoring import (
    FeatureObservation, PostgameSignal, PregameSignal, VersionedScore,
    score_postgame, score_pregame,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


class SqlAlchemyRankingEvidenceRepository:
    """Read only curated `ranking.{kind}.{signal}` facts for canonical NBA games.

    A producer must populate a TemporalFactRecord with subject_type="game",
    value={"normalized_value": number in [0, 1]}, its source_id, and real
    validity/availability/observation timestamps. The collector/provider's
    unnormalized payload is NOT an input to this service.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _game_observation(
        self, game_id: UUID, as_of: datetime,
    ) -> GameObservationRecord | None:
        # Choose latest knowable observation BEFORE inspecting status. Otherwise
        # an older 'scheduled' or 'final' row could survive a known correction.
        observations = (await self._session.scalars(
            select(GameObservationRecord)
            .join(GameRecord, GameRecord.id == GameObservationRecord.game_id)
            .join(SeasonRecord, SeasonRecord.id == GameRecord.season_id)
            .where(
                GameObservationRecord.game_id == game_id,
                SeasonRecord.league == "NBA",
                GameObservationRecord.observed_at <= as_of,
                GameObservationRecord.available_at <= as_of,
            )
            .order_by(GameObservationRecord.observed_at.desc(),
                      GameObservationRecord.available_at.desc(),
                      GameObservationRecord.id.desc())
            .limit(2)
        )).all()
        if not observations:
            return None
        if (len(observations) > 1
                and observations[0].observed_at == observations[1].observed_at
                and observations[0].available_at == observations[1].available_at):
            # Competing latest observations have no defensible winner; never
            # infer a trusted scheduled tip or final state from UUID ordering.
            return None
        # Check provenance AFTER choosing the latest observation: a newer
        # unverified revision must mask older data, not resurrect it.
        source = await self._session.get(SourceRecord, observations[0].source_id)
        if source is None or source.verification_status != "verified":
            return None
        return observations[0]

    async def _features(
        self, game_id: UUID, as_of: datetime, kind: str,
    ) -> dict[PregameSignal, FeatureObservation] | dict[PostgameSignal, FeatureObservation]:
        family = PregameSignal if kind == "pregame" else PostgameSignal
        mapping = {f"ranking.{kind}.{signal.value}": signal for signal in family}
        facts = (await self._session.scalars(
            select(TemporalFactRecord)
            .where(
                TemporalFactRecord.subject_type == "game",
                TemporalFactRecord.game_id == game_id,
                TemporalFactRecord.fact_type.in_(mapping),
                TemporalFactRecord.available_at <= as_of,
                TemporalFactRecord.observed_at <= as_of,
                TemporalFactRecord.valid_from <= as_of,
                or_(TemporalFactRecord.valid_to.is_(None),
                    TemporalFactRecord.valid_to > as_of),
            )
            .order_by(TemporalFactRecord.observed_at.desc(),
                      TemporalFactRecord.available_at.desc(),
                      TemporalFactRecord.id.desc())
        )).all()
        latest: dict[str, TemporalFactRecord] = {}
        ambiguous: set[str] = set()
        for fact in facts:
            previous = latest.get(fact.fact_type)
            if previous is None:
                latest[fact.fact_type] = fact
            elif (fact.observed_at == previous.observed_at
                  and fact.available_at == previous.available_at):
                # A same-time competing revision must not be chosen by UUID.
                ambiguous.add(fact.fact_type)

        # Verify the original registry identity, not a claim in the JSON
        # feature value. A revoked/unreviewed latest fact masks earlier facts.
        source_ids = {fact.source_id for fact in latest.values()}
        verified_sources = set()
        if source_ids:
            source_rows = (await self._session.execute(
                select(SourceRecord.id)
                .where(SourceRecord.id.in_(source_ids),
                       SourceRecord.verification_status == "verified")
            )).scalars().all()
            verified_sources = set(source_rows)

        signals = {}
        for fact_type, fact in latest.items():
            # Tied, unverified and malformed latest revisions mask older values.
            if fact_type in ambiguous or fact.source_id not in verified_sources:
                continue
            if (type(fact.value) is not dict
                    or set(fact.value) != {"normalized_value"}):
                continue
            try:
                feature = FeatureObservation(
                    value=fact.value["normalized_value"],
                    source_ref=f"temporal_fact:{fact.source_id}:{fact.id}",
                    available_at=fact.available_at,
                    observed_at=fact.observed_at,
                )
            except (TypeError, ValueError):
                continue
            signals[mapping[fact_type]] = feature
        return signals

    async def pregame(
        self, game_id: UUID, *, as_of: datetime,
    ) -> VersionedScore | None:
        cursor = _utc(as_of)
        if cursor is None:
            raise ValueError("as_of must be timezone-aware")
        observation = await self._game_observation(game_id, cursor)
        if (
            observation is None
            or observation.status != "scheduled"
            or observation.home_score is not None
            or observation.away_score is not None
            or observation.actual_tip_at is not None
            or observation.final_at is not None
        ):
            # A scheduled row carrying a score, actual start or final marker
            # is not a trustworthy pre-tip state, even from a reviewed source.
            return None
        tip = _utc(observation.scheduled_tip_at)
        if (tip is None or cursor >= tip
                or _utc(observation.observed_at) is None
                or _utc(observation.observed_at) >= tip
                or _utc(observation.available_at) is None
                or _utc(observation.available_at) >= tip):
            return None
        features = await self._features(game_id, cursor, "pregame")
        if not features:
            return None
        return score_pregame(game_id, features, tip_at=tip, as_of=cursor)

    async def postgame(
        self, game_id: UUID, *, as_of: datetime,
    ) -> VersionedScore | None:
        cursor = _utc(as_of)
        if cursor is None:
            raise ValueError("as_of must be timezone-aware")
        observation = await self._game_observation(game_id, cursor)
        if observation is None or observation.status != "final":
            return None
        final = _utc(observation.final_at)
        observed = _utc(observation.observed_at)
        available = _utc(observation.available_at)
        scheduled_tip = _utc(observation.scheduled_tip_at)
        actual_tip = _utc(observation.actual_tip_at)
        if (final is None or final > cursor or observed is None
                or observed < final or available is None or available < final
                or (scheduled_tip is not None and final <= scheduled_tip)
                or (actual_tip is not None and final <= actual_tip)):
            # A final marker must follow every known tip boundary. Otherwise
            # even source-reviewed data cannot establish a real postgame window.
            return None
        features = await self._features(game_id, cursor, "postgame")
        # Drop facts with pre-final evidence without silently losing valid ones.
        features = {
            signal: feature for signal, feature in features.items()
            if (_utc(feature.available_at) is not None
                and _utc(feature.available_at) >= final
                and _utc(feature.observed_at) is not None
                and _utc(feature.observed_at) >= final)
        }
        if not features:
            return None
        return score_postgame(game_id, features, final_at=final, as_of=cursor)
