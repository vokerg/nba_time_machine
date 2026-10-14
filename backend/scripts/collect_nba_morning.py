"""One NBA-day morning pass. Default: read-only health/counts, no database access."""
import argparse
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from nba_time_machine.sports.morning import MorningCollector, PublicNBAClient
from nba_time_machine.sports.morning_models import EASTERN


async def run(args):
    async with httpx.AsyncClient() as http:
        collector = MorningCollector(PublicNBAClient(http, max_requests=args.max_requests),
                                     max_games=args.max_games, provider=args.provider)
        if args.write:
            from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
            from nba_time_machine.sports.morning_store import MorningStore
            engine = create_database_engine(DatabaseSettings())
            try:
                result = await MorningStore(create_session_factory(engine), manual=args.manual).collect(
                    collector, args.date, game_id=args.game)
            finally:
                await engine.dispose()
        else:
            result = await collector.collect(args.date, game_id=args.game)
    output = json.dumps(result.diagnostics(), indent=2)
    print(output)
    if args.report:
        args.report.write_text(output + "\n")
    # Empty, verified ESPN slates succeed. Pending, missing or partial games remain visible failures.
    return 2 if (result.errors or result.persistence_errors or any(
        g.selected("pbp") is None or g.selected("box") is None for g in result.games)) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat,
                        default=datetime.now(EASTERN).date() - timedelta(days=1))
    parser.add_argument("--game", help="Optional exact ESPN ID or CBS game abbreviation on this NBA date")
    parser.add_argument("--provider", choices=("espn", "cbs"), default="espn",
                        help="Primary normally ESPN; CBS permits a bounded backup smoke")
    parser.add_argument("--max-requests", type=int, choices=range(1, 101), default=40, metavar="1..100")
    parser.add_argument("--max-games", type=int, choices=range(1, 21), default=20, metavar="1..20")
    parser.add_argument("--write", action="store_true", help="Explicitly persist using configured PostgreSQL and reviewed registry policies")
    parser.add_argument("--manual", action="store_true", help="With --write, allow verified disabled sources without enabling scheduling")
    parser.add_argument("--report", type=Path, help="Write health/count diagnostics, never full source content")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except Exception:
        raise SystemExit("Morning collection failed; inspect configuration/database access. No source bodies or secrets logged.") from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
