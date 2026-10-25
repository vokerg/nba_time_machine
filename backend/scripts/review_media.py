"""Local-only media review queue. No HTTP endpoint and no automatic clearance.

From backend/ (requires DATABASE_URL and applied migrations):
    python scripts/review_media.py pending --source-id APPROVED_SOURCE
    python scripts/review_media.py inspect CAPTURE_UUID
    python scripts/review_media.py approve CAPTURE_UUID --hash EXACT_64_CHAR_HASH \
        --sensitivity general --rights-cleared --complete-links-reviewed

The operator must separately verify publisher rights and inspect the *exact*
revision, including all game associations and spoiler-bearing headlines.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.ingestion.media_review_ops import (
    ReviewDecision, ReviewRejected, approve_review, inspect_review, pending_reviews,
)


async def run(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    if not settings.is_configured:
        raise SystemExit("DATABASE_URL is required (migrated PostgreSQL)")
    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            if args.command == "pending":
                payload = await pending_reviews(session, limit=args.limit, source_id=args.source_id)
            elif args.command == "inspect":
                payload = await inspect_review(session, args.capture_id)
            else:
                if not args.complete_links_reviewed:
                    raise ReviewRejected("review all related games before approval")
                decision = ReviewDecision(
                    capture_id=args.capture_id, content_hash=args.hash,
                    sensitivity=args.sensitivity, game_ids=tuple(args.game_id),
                    rights_cleared=args.rights_cleared, link_cleared=args.link_cleared,
                )
                async with session.begin():
                    stamp = await approve_review(session, decision)
                payload = {"approved_capture_id": str(args.capture_id), "reviewed_at": stamp.isoformat()}
        print(json.dumps(payload, sort_keys=True))
        return 0
    except ReviewRejected as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}, sort_keys=True))
        return 2
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("pending", help="List pending revision IDs, hashes and timestamps")
    pending.add_argument("--source-id", help="Restrict to a single reviewed source")
    pending.add_argument("--limit", type=int, default=25)
    inspect = commands.add_parser("inspect", help="Locally display one unreviewed title/excerpt (spoilers)")
    inspect.add_argument("capture_id", type=UUID)
    approve = commands.add_parser("approve", help="Explicitly clear one exact revision")
    approve.add_argument("capture_id", type=UUID)
    approve.add_argument("--hash", required=True, help="Exact content_hash copied from inspect")
    approve.add_argument("--sensitivity", required=True,
                         choices=("general", "pregame", "outcome_dependent"))
    approve.add_argument("--game-id", type=UUID, action="append", default=[],
                         help="Repeat for every associated game, including hidden others")
    approve.add_argument("--rights-cleared", action="store_true",
                         help="I independently verified this publisher permits this display")
    approve.add_argument("--link-cleared", action="store_true",
                         help="I independently verified this individual HTTPS link is publishable")
    approve.add_argument("--complete-links-reviewed", action="store_true",
                         help="I checked the full headline/excerpt and ALL game associations")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
