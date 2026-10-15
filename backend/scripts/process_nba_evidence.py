"""Derive features and hidden ratings from stored morning evidence; dry-run default."""
import argparse
import asyncio
import json
from uuid import UUID

from archive_ranking import parse_as_of
from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline


async def run(args):
    engine = create_database_engine(DatabaseSettings())
    try:
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            eligible = await MorningRankingPipeline(session).process(
                args.game_id, as_of=args.as_of, write=args.write)
        print(json.dumps({"eligible": eligible, "write": args.write,
                          "score_archived": eligible and args.write}))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", type=UUID, required=True)
    parser.add_argument("--as-of", type=parse_as_of, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception:
        raise SystemExit("Evidence processing failed; inspect configuration or revision conflicts. No content logged.") from None


if __name__ == "__main__":
    main()
