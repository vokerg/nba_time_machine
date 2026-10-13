"""Additive, repeatable TheSportsDB NBA collection into configured PostgreSQL."""
import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.sports.collection import SEASONS, SportsCollector, validate_window
from nba_time_machine.sports.config import SportsProviderSettings
from nba_time_machine.sports.thesportsdb import TheSportsDBClient


async def run(args):
    validate_window(args.season, args.start, args.end)
    engine = create_database_engine(DatabaseSettings())
    settings = SportsProviderSettings(_env_file=".env")
    try:
        async with TheSportsDBClient(settings) as client:
            result = await SportsCollector(create_session_factory(engine), client,
                         max_requests=args.max_requests, manual=args.manual).collect(
                         args.season, start=args.start, end=args.end, statistics=args.statistics)
            output = json.dumps(asdict(result), indent=2)
            print(output)
            if args.report:
                args.report.write_text(output + '\n')
    finally:
        await engine.dispose()


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', required=True, choices=SEASONS)
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--max-requests', type=int, default=400)
    parser.add_argument('--statistics', action='store_true')
    parser.add_argument('--manual', action='store_true', help='Explicit operator run of verified source, even if scheduling disabled')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception:
        # Never render exceptions that may contain credential-bearing request URLs.
        raise SystemExit('Collection failed; inspect source policy, database access and configuration. No secrets logged.') from None


if __name__ == '__main__':
    main()
