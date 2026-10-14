from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db import (
    GameObservationRecord,
    GameRecord,
    SeasonRecord,
    SourceRecord,
    SportsExternalIdentityRecord,
    TeamRecord,
)
from nba_time_machine.sports.contracts import (
    NormalizedGameObservation,
    NormalizedProviderTeam,
)
from nba_time_machine.sports.errors import SportsProviderResponseError
from nba_time_machine.sports.normalize import normalize_thesportsdb_event

PROVIDER_KEY = "thesportsdb"
LEAGUE = "NBA"


class StructuredSportsStore:
    """Persist provider-normalized sports data without overwriting history."""

    def __init__(
        self,
        *,
        source_id: str = "thesportsdb-nba",
        provider_key: str = PROVIDER_KEY,
        reconcile_existing: bool = False,
    ) -> None:
        self._source_id = source_id
        self._provider_key = provider_key
        self._reconcile_existing = reconcile_existing

    async def store_thesportsdb_event(
        self,
        session: AsyncSession,
        event: dict[str, object],
        *,
        observed_at: datetime,
    ) -> GameObservationRecord:
        normalized = normalize_thesportsdb_event(event)
        return await self.store_game_observation(
            session,
            normalized,
            observed_at=observed_at,
        )

    async def store_game_observation(
        self,
        session: AsyncSession,
        normalized: NormalizedGameObservation,
        *,
        observed_at: datetime,
    ) -> GameObservationRecord:
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")

        source = await session.get(SourceRecord, self._source_id)
        if source is None:
            raise SportsProviderResponseError(
                f"Structured sports source {self._source_id!r} is not in the registry"
            )

        game = await self.resolve_game_identity(session, normalized)

        existing = await session.scalar(
            select(GameObservationRecord).where(
                GameObservationRecord.game_id == game.id,
                GameObservationRecord.source_id == self._source_id,
                GameObservationRecord.observed_at == observed_at,
            )
        )
        if existing is not None:
            # The timestamp identifies a single historical capture, not an
            # overwrite slot. Exact retries are safe; contradictory payloads
            # at the same source/time must not silently retain stale facts.
            if (
                existing.status != normalized.status
                or existing.scheduled_tip_at != normalized.scheduled_tip_at
                or existing.home_score != normalized.home_score
                or existing.away_score != normalized.away_score
                or existing.observation_metadata != normalized.metadata
                or existing.available_at != observed_at
                or existing.actual_tip_at is not None
                or existing.final_at is not None
            ):
                raise SportsProviderResponseError(
                    "Conflicting TheSportsDB observation at the same source and observation time"
                )
            return existing

        observation = GameObservationRecord(
            game_id=game.id,
            source_id=self._source_id,
            observed_at=observed_at,
            available_at=observed_at,
            status=normalized.status,
            scheduled_tip_at=normalized.scheduled_tip_at,
            actual_tip_at=None,
            final_at=None,
            home_score=normalized.home_score,
            away_score=normalized.away_score,
            observation_metadata=normalized.metadata,
        )
        session.add(observation)
        await session.flush()
        return observation

    async def resolve_game_identity(self, session: AsyncSession, normalized: NormalizedGameObservation) -> GameRecord:
        """Resolve provider mappings, optionally joining an existing dated matchup."""
        season = await self._ensure_season(session, normalized.season_label)
        home = await self._ensure_team(session, normalized.home_team)
        away = await self._ensure_team(session, normalized.away_team)
        return await self._ensure_game(session, normalized, season_id=season.id,
                                      home_team_id=home.id, away_team_id=away.id)

    async def _ensure_season(
        self,
        session: AsyncSession,
        label: str,
    ) -> SeasonRecord:
        season = await session.scalar(
            select(SeasonRecord).where(
                SeasonRecord.league == LEAGUE,
                SeasonRecord.label == label,
            )
        )
        if season is not None:
            return season

        season = SeasonRecord(league=LEAGUE, label=label)
        session.add(season)
        await session.flush()
        return season

    async def _ensure_team(
        self,
        session: AsyncSession,
        team: NormalizedProviderTeam,
    ) -> TeamRecord:
        mapping = await self._external_identity(
            session,
            entity_type="team",
            external_id=team.external_id,
        )
        if mapping is not None:
            if mapping.team_id is None:
                raise SportsProviderResponseError(
                    "Provider team identity does not point to a team"
                )
            record = await session.get(TeamRecord, mapping.team_id)
            if record is None:
                raise SportsProviderResponseError(
                    "Provider team identity points to a missing team"
                )
            if self._reconcile_existing:
                aliases = {"Los Angeles Clippers": "LA Clippers"}
                if record.league != LEAGUE or aliases.get(record.name, record.name).casefold() != team.name.casefold():
                    raise SportsProviderResponseError("Provider team identity changed canonical team")
            return record

        record = None
        if self._reconcile_existing:
            names = {team.name.casefold()}
            if team.name in ("LA Clippers", "Los Angeles Clippers"):
                names.update(("la clippers", "los angeles clippers"))
            candidates = list((await session.scalars(select(TeamRecord).where(
                TeamRecord.league == LEAGUE, func.lower(TeamRecord.name).in_(names),
            ))).all())
            if len(candidates) > 1:
                raise SportsProviderResponseError("Ambiguous canonical team identity")
            record = candidates[0] if candidates else None
        if record is None:
            record = TeamRecord(league=LEAGUE, name=team.name, abbreviation=None)
            session.add(record)
            await session.flush()
        session.add(
            SportsExternalIdentityRecord(
                provider_key=self._provider_key,
                entity_type="team",
                external_id=team.external_id,
                team_id=record.id,
            )
        )
        await session.flush()
        return record

    async def _ensure_game(
        self,
        session: AsyncSession,
        normalized: NormalizedGameObservation,
        *,
        season_id: UUID,
        home_team_id: UUID,
        away_team_id: UUID,
    ) -> GameRecord:
        mapping = await self._external_identity(
            session,
            entity_type="game",
            external_id=normalized.external_event_id,
        )
        if mapping is not None:
            if mapping.game_id is None:
                raise SportsProviderResponseError(
                    "Provider game identity does not point to a game"
                )
            game = await session.get(GameRecord, mapping.game_id)
            if game is None:
                raise SportsProviderResponseError(
                    "Provider game identity points to a missing game"
                )
            if (
                game.season_id != season_id
                or game.home_team_id != home_team_id
                or game.away_team_id != away_team_id
            ):
                raise SportsProviderResponseError(
                    "Provider game identity changed season or team identity"
                )
            return game

        game = None
        if self._reconcile_existing:
            from nba_time_machine.sports.morning_models import EASTERN
            if normalized.scheduled_tip_at is None:
                raise SportsProviderResponseError("Missing matchup date for canonical matching")
            nba_day = normalized.scheduled_tip_at.astimezone(EASTERN).date()
            start = datetime.combine(nba_day, time(), EASTERN)
            candidates = list((await session.scalars(select(GameRecord).join(
                GameObservationRecord, GameObservationRecord.game_id == GameRecord.id,
            ).where(
                GameRecord.season_id == season_id,
                GameRecord.home_team_id == home_team_id,
                GameRecord.away_team_id == away_team_id,
                GameObservationRecord.scheduled_tip_at >= start,
                GameObservationRecord.scheduled_tip_at < start + timedelta(days=1),
            ).distinct())).all())
            if len(candidates) > 1:
                raise SportsProviderResponseError("Ambiguous canonical game identity")
            game = candidates[0] if candidates else None
        if game is None:
            game = GameRecord(season_id=season_id, home_team_id=home_team_id,
                              away_team_id=away_team_id, game_type=None)
            session.add(game)
            await session.flush()
        session.add(
            SportsExternalIdentityRecord(
                provider_key=self._provider_key,
                entity_type="game",
                external_id=normalized.external_event_id,
                game_id=game.id,
            )
        )
        await session.flush()
        return game

    async def _external_identity(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        external_id: str,
    ) -> SportsExternalIdentityRecord | None:
        return await session.scalar(
            select(SportsExternalIdentityRecord).where(
                SportsExternalIdentityRecord.provider_key == self._provider_key,
                SportsExternalIdentityRecord.entity_type == entity_type,
                SportsExternalIdentityRecord.external_id == external_id,
            )
        )
