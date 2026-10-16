#!/usr/bin/env python
"""Explicit bounded manual import. No fetch, scheduler, policy changes or backdating."""
import argparse
import asyncio
import json
from pathlib import Path

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.ranking.player_rankings import RankingImport
from nba_time_machine.ranking.player_ranking_store import import_snapshot


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    if args.snapshot.stat().st_size > 256_000:
        parser.error('snapshot exceeds 256 KB')
    payload = RankingImport.model_validate_json(args.snapshot.read_text())
    engine = create_database_engine(DatabaseSettings())
    try:
        async with create_session_factory(engine).begin() as session:
            print(json.dumps(await import_snapshot(session, payload, write=args.write)))
    except ValueError as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}))
        raise SystemExit(2) from None
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
