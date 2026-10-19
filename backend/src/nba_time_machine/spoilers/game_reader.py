"""Read trusted game snapshots from historical observations, never client fields."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_time_machine.db import GameObservationRecord, GameRecord, TeamRecord
from nba_time_machine.spoilers.policy import GameField, GameFieldName
from nba_time_machine.spoilers.service import TrustedGameSnapshot


def utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


class SqlAlchemyGameSnapshotRepository:
    def __init__(self, session: AsyncSession, *, observed_schedule: bool = False, season_replay: bool = False, knowledge_bounded: bool = False) -> None:
        self.knowledge_bounded = knowledge_bounded
        self.session = session
        self.observed_schedule = observed_schedule
        self.season_replay = season_replay

    async def get(self, game_id: UUID, *, time_cursor: datetime) -> TrustedGameSnapshot | None:
        game = await self.session.get(GameRecord, game_id)
        if game is None:
            return None
        observations = list((await self.session.scalars(
            select(GameObservationRecord)
            .where(GameObservationRecord.game_id == game_id)
            .order_by(GameObservationRecord.observed_at, GameObservationRecord.id)
        )).all())
        cursor = utc(time_cursor)
        if cursor is None:
            raise ValueError("cursor must be timezone-aware")

        if self.knowledge_bounded:
            # Guide disclosures cannot use legacy explicit-reveal exceptions.
            observations = [item for item in observations
                            if utc(item.available_at) is not None and utc(item.observed_at) is not None
                            and utc(item.available_at) <= cursor and utc(item.observed_at) <= cursor]

        pregame = []
        for item in observations:
            tip = utc(item.scheduled_tip_at)
            available, observed = utc(item.available_at), utc(item.observed_at)
            if (tip is not None and available is not None and observed is not None
                    and available < tip and observed < tip
                    and available <= cursor and observed <= cursor):
                pregame.append(item)
        safe = pregame[-1] if pregame else None
        if self.observed_schedule:
            # No status/result filtering: membership must not depend on who won,
            # whether final results exist, or other outcome-bearing information.
            known = [item for item in observations
                     if utc(item.available_at) is not None and utc(item.observed_at) is not None
                     and utc(item.available_at) <= cursor and utc(item.observed_at) <= cursor]
            safe = known[-1] if known else None
        if self.season_replay:
            timestamped = [item for item in observations
                           if utc(item.available_at) is not None and utc(item.observed_at) is not None]
            safe = timestamped[-1] if timestamped else None
        tip = utc(safe.scheduled_tip_at) if safe is not None else next(
            (ts for item in observations
             if (ts := utc(item.actual_tip_at) or utc(item.scheduled_tip_at)) is not None),
            None,
        )

        result_observations = observations
        if self.knowledge_bounded:
            # Select the latest revision before considering its final status.
            # A later correction must mask an older final result.
            result_observations = observations[-1:]
            if len(observations) > 1 and observations[-1].observed_at == observations[-2].observed_at:
                result_observations = []
        completed = [item for item in result_observations
                     if item.status == "final" and utc(item.available_at) is not None
                     and utc(item.observed_at) is not None]
        boundaries = []
        for item in completed:
            boundary = max(utc(item.available_at), utc(item.observed_at),
                           utc(item.final_at) or utc(item.observed_at))
            if tip is not None and boundary > tip:
                boundaries.append(boundary)
        complete_scores = [item for item in completed
                           if item.home_score is not None and item.away_score is not None]
        final = complete_scores[-1] if complete_scores else None

        fields: list[GameField] = []
        if safe is not None:
            home = await self.session.get(TeamRecord, game.home_team_id)
            away = await self.session.get(TeamRecord, game.away_team_id)
            if home is not None:
                fields.append(GameField(GameFieldName.HOME_TEAM, home.name,
                                        safe.available_at, safe.observed_at))
            if away is not None:
                fields.append(GameField(GameFieldName.AWAY_TEAM, away.name,
                                        safe.available_at, safe.observed_at))
            fields.append(GameField(GameFieldName.SCHEDULED_TIP,
                                    utc(safe.scheduled_tip_at).isoformat() if utc(safe.scheduled_tip_at) else None,
                                    safe.available_at, safe.observed_at))

        if final is not None:
            for name, value in (
                (GameFieldName.IN_GAME_STATUS, "final"),
                (GameFieldName.HOME_SCORE, final.home_score),
                (GameFieldName.AWAY_SCORE, final.away_score),
            ):
                fields.append(GameField(name, value, final.available_at, final.observed_at))
            if final.home_score != final.away_score:
                outcome = "Home won" if final.home_score > final.away_score else "Away won"
                fields.append(GameField(GameFieldName.RESULT, outcome,
                                        final.available_at, final.observed_at))
        return TrustedGameSnapshot(
            game_id=game_id, tip_at=tip,
            protection_ends_at=min(boundaries) if boundaries else None,
            fields=tuple(fields), full_available=final is not None,
        )
