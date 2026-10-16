"""Bounded private hobby Top 100 update; durable minimum interval is fourteen days."""
import argparse
import asyncio
import json

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.ingestion.ringer import configure_hobby_source, refresh_if_due, complete_identities


async def run(configure):
    engine = create_database_engine(DatabaseSettings())
    try:
        factory = create_session_factory(engine)
        if configure:
            await configure_hobby_source(factory)
        print(json.dumps(await refresh_if_due(factory)))
        print(json.dumps(await complete_identities(factory)))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure-private-hobby', action='store_true',
        help='Explicit owner-directed setup; acknowledges terms restriction, not a publisher license')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.configure_private_hobby))
    except Exception:
        raise SystemExit('Ringer operation unavailable; no source bodies or credentials logged.') from None
