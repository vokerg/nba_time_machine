"""Run one bounded, policy-aware RSS/web collection pass.

Usage (from backend/, after migrating PostgreSQL and verifying/enabling sources):
    python scripts/collect_sources.py --source-id approved-rss-source
    python scripts/collect_sources.py --source-id approved-rss-source --force
"""

from __future__ import annotations

import argparse
import asyncio
import json

from nba_time_machine.db import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from nba_time_machine.ingestion.runtime import collect_once


async def run(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    if not settings.is_configured:
        raise SystemExit("DATABASE_URL must point to an Alembic-migrated PostgreSQL database")
    engine = create_database_engine(settings)
    try:
        summary = await collect_once(
            create_session_factory(engine),
            source_ids=args.source_id or None,
            concurrency=args.concurrency,
            force=args.force,
        )
        print(json.dumps({
            "run_id": str(summary.run_id),
            "outcomes": [result.__dict__ for result in summary.outcomes],
        }, sort_keys=True))
        return int(any(
            outcome.status not in {"ok", "idle", "skipped_config"}
            for outcome in summary.outcomes
        ))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", action="append", help="Limit to reviewed source ID; repeatable")
    parser.add_argument("--force", action="store_true", help="Bypass cadence, never source verification")
    parser.add_argument("--concurrency", type=int, default=4, help="Between 1 and 16")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
