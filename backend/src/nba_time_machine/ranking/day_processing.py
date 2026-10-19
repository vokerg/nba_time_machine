"""Bounded publication of the existing model from canonical stored day evidence."""
from sqlalchemy import select

from nba_time_machine.db import TemporalFactRecord
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline


async def process_stored_day(factory, day, *, as_of):
    async with factory() as session:
        games = list((await session.scalars(select(TemporalFactRecord.game_id).where(
            TemporalFactRecord.subject_type == "game",
            TemporalFactRecord.fact_type == "provider_game_evidence",
            TemporalFactRecord.value["ref"]["day"].astext == day.isoformat(),
            TemporalFactRecord.observed_at <= as_of,
            TemporalFactRecord.available_at <= as_of,
        ).distinct().order_by(TemporalFactRecord.game_id).limit(21))).all())
    if len(games) > 20:
        raise ValueError("day_game_limit")
    eligible = failed = 0
    for game in games:
        try:
            async with factory.begin() as session:
                ready = await MorningRankingPipeline(session).process(
                    game, as_of=as_of, write=True, slate_date=day)
            eligible += int(ready)
        except Exception:
            # Other games still commit. Never serialize exception/source bodies.
            failed += 1
    return {"games": len(games), "eligible": eligible,
            "unavailable": len(games) - eligible - failed, "failed": failed}
