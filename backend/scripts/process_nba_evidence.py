"""Derive features and hidden ratings from stored morning evidence; dry-run default."""
import argparse
import asyncio
import json
from datetime import date
from uuid import UUID

from archive_ranking import parse_as_of
from sqlalchemy import select
from nba_time_machine.db import DatabaseSettings, TemporalFactRecord, create_database_engine, create_session_factory
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline


async def run(args):
    engine = create_database_engine(DatabaseSettings())
    try:
        factory = create_session_factory(engine)
        if args.game_id:
            games = [args.game_id]
        else:
            async with factory() as session:
                games = list((await session.scalars(select(TemporalFactRecord.game_id).where(
                    TemporalFactRecord.subject_type == "game",
                    TemporalFactRecord.fact_type == "provider_game_evidence",
                    TemporalFactRecord.value["ref"]["day"].astext == args.date.isoformat(),
                    TemporalFactRecord.observed_at <= args.as_of,
                    TemporalFactRecord.available_at <= args.as_of,
                ).distinct().order_by(TemporalFactRecord.game_id).limit(21))).all())
            if len(games) > 20:
                raise ValueError("more than 20 games; process explicit game IDs")
        eligible = failed = 0
        for game in games:
            try:
                # Independent game transactions preserve unrelated successes.
                async with factory.begin() as session:
                    pipeline = MorningRankingPipeline(session)
                    ready = await pipeline.process(
                        game, as_of=args.as_of, write=args.write, slate_date=args.date)
                eligible += int(ready)
            except Exception:
                failed += 1
        print(json.dumps({"games": len(games), "eligible": eligible,
                          "unavailable": len(games) - eligible - failed,
                          "failed": failed, "write": args.write,
                          "scores_archived": eligible if args.write else 0}))
        return 2 if failed or eligible != len(games) else 0
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--game-id", type=UUID)
    target.add_argument("--date", type=date.fromisoformat, help="Eastern NBA day of stored evidence (max 20 games)")
    parser.add_argument("--as-of", type=parse_as_of, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except Exception:
        raise SystemExit("Evidence processing failed; inspect configuration or revision conflicts. No content logged.") from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
