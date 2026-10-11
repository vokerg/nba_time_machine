"""Synchronize reviewed source definitions; optionally print runtime source health.

Use --validate-only for offline seed checks. No network collectors are launched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.ingestion.registry import (
    SourceSeed,
    list_source_health,
    load_source_seed,
    sync_source_seed,
)

DEFAULT_SEED = Path(__file__).resolve().parents[2] / "config" / "sources.seed.json"


async def reconcile(seed: SourceSeed, show_health: bool) -> None:
    settings = DatabaseSettings()
    if not settings.is_configured:
        raise SystemExit("DATABASE_URL must be configured to synchronize sources")

    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            result = await sync_source_seed(session, seed)
        print(f"Configured: {result.configured}; inserted or changed: {result.changed}")
        if show_health:
            async with factory() as session:
                health = await list_source_health(session)
            for source in health:
                print(json.dumps(asdict(source), default=str, sort_keys=True))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate/sync reviewed sources into PostgreSQL")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--health", action="store_true", help="Print source health after syncing")
    args = parser.parse_args()
    seed = load_source_seed(args.seed)
    if args.validate_only:
        print(f"Valid seed: {len(seed.sources)} unique sources")
        return
    asyncio.run(reconcile(seed, args.health))


if __name__ == "__main__":
    main()
