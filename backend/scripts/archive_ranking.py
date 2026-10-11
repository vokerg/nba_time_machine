"""Materialize one trusted ranking score snapshot (no score values on stdout).

Requires an explicit canonical game ID, score family and as-of timestamp.
For postgame, trusted final evidence and normalized features must already be
stored. This is an internal operator action, not a spoiler-safe public read.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from uuid import UUID

from nba_time_machine.db import (
    DatabaseSettings, create_database_engine, create_session_factory,
)
from nba_time_machine.ranking.evidence import SqlAlchemyRankingEvidenceRepository
from nba_time_machine.ranking.materialize import RankingMaterializationService
from nba_time_machine.ranking.repository import SqlAlchemyRankingStore
from nba_time_machine.ranking.scoring import ScoreKind


def parse_as_of(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected ISO-8601 timestamp with UTC offset") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("as-of timestamp must include a timezone offset")
    return stamp


async def materialize(game_id: UUID, kind: ScoreKind, as_of: datetime) -> bool:
    settings = DatabaseSettings()
    if not settings.is_configured:
        raise SystemExit("DATABASE_URL must be configured to materialize ranking scores")
    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory.begin() as session:
            service = RankingMaterializationService(
                SqlAlchemyRankingEvidenceRepository(session),
                SqlAlchemyRankingStore(session),
            )
            return await service.materialize(game_id, kind=kind, as_of=as_of)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive one historically trusted ranking snapshot (internal only)"
    )
    parser.add_argument("--game-id", type=UUID, required=True)
    parser.add_argument("--kind", choices=[kind.value for kind in ScoreKind], required=True)
    parser.add_argument("--as-of", type=parse_as_of, required=True,
                        help="ISO-8601 instant with explicit timezone offset")
    args = parser.parse_args()
    stored = asyncio.run(materialize(args.game_id, ScoreKind(args.kind), args.as_of))
    if stored:
        print("Trusted ranking snapshot archived or already identical.")
    else:
        print("No trusted evidence for this game/kind/as-of; nothing archived.")


if __name__ == "__main__":
    main()
