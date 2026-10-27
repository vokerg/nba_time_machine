"""Explicit prior-season foundation collection, without recalculating any ratings."""
import argparse
import asyncio
from datetime import date
import json
import os
from pathlib import Path

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.sports.season_foundation_store import ensure_foundation


async def run(args):
    engine = create_database_engine(DatabaseSettings())
    try:
        return await ensure_foundation(create_session_factory(engine), args.date, force=args.force)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat, required=True, help='A date in the season to rate')
    parser.add_argument('--write', action='store_true', help='Explicitly fetch and save normalized prior evidence')
    parser.add_argument('--force', action='store_true', help='Explicitly recheck a previously saved foundation')
    args = parser.parse_args()
    if not args.write:
        parser.error('--write is required; no collection is performed on read paths')
    os.chdir(Path(__file__).resolve().parents[1])
    result = asyncio.run(run(args))
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] in ('stored', 'collected') else 2)
