"""Collect normalized regular-season results for retrospective matchup context."""
import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import httpx

from nba_time_machine.sports.history_collection import collect_and_store, collect_history
from nba_time_machine.sports.morning import PublicNBAClient
from nba_time_machine.sports.standings_history import START


async def run(args):
    async with httpx.AsyncClient() as http:
        client = PublicNBAClient(http, max_requests=args.max_requests)
        if args.write:
            from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
            engine = create_database_engine(DatabaseSettings())
            try:
                result = await collect_and_store(create_session_factory(engine), client,
                    args.start, args.date - timedelta(days=1), manual=args.manual)
            finally:
                await engine.dispose()
        else:
            result = await collect_history(client, args.start, args.date - timedelta(days=1))
    output = json.dumps(result.diagnostics(), indent=2)
    print(output)
    if args.report:
        args.report.write_text(output + "\n")
    return 2 if result.errors or result.persistence_errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="Target NBA day; collect only earlier days")
    parser.add_argument("--start", type=date.fromisoformat, default=START, help="Explicit chunk start; default reviewed season opening day")
    parser.add_argument("--max-requests", type=int, choices=range(1, 101), default=40)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except Exception:
        raise SystemExit("History collection unavailable: check reviewed calendar, request budget, source policy and database. No content or secrets logged.") from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
