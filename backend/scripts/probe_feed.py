"""Manual, research-only RSS/Atom structural probe for Issue #9.

Default mode reads a local fixture. Live mode requires an explicit confirmation
of source-specific access, robots, rate and retention review. No ingest or writes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from nba_time_machine.ingestion.adapters import CollectionFailure
from nba_time_machine.ingestion.feed_probe import inspect_file, probe_live
from nba_time_machine.ingestion.registry import load_source_seed

DEFAULT_SEED = Path(__file__).resolve().parents[2] / "config" / "sources.seed.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--source-id", required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--file", type=Path, help="Read only a saved XML feed fixture")
    choice.add_argument("--live", action="store_true", help="Make one bounded HTTPS GET")
    parser.add_argument(
        "--access-reviewed", action="store_true",
        help="Required for --live: operator has reviewed access/robots/rights/rate policy",
    )
    args = parser.parse_args()

    if args.live and not args.access_reviewed:
        parser.error("--live requires --access-reviewed after independent policy review")

    try:
        seed = load_source_seed(args.seed)
        source = next((s for s in seed.sources if s.id == args.source_id), None)
        if source is None:
            print(json.dumps({"status": "skipped_config", "code": "unknown_source"}))
            return 2
        if args.live:
            result = asyncio.run(probe_live(source, access_reviewed=args.access_reviewed))
        else:
            result = inspect_file(source, args.file)
        print(json.dumps(result, sort_keys=True))
        return 0
    except CollectionFailure as exc:
        print(json.dumps({"status": exc.status, "code": exc.code}, sort_keys=True))
        return 2
    except (OSError, UnicodeError, ValueError):
        # Intentionally do not log local paths, exception text, feed contents or URLs.
        print(json.dumps({"status": "skipped_config", "code": "input_error"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
