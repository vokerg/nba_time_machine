"""Generate deterministic, policy-filtered JSON fixtures for the React dashboard.

From backend/: PYTHONPATH=src python scripts/export_read_model_fixtures.py
The inputs are deliberately synthetic; this is not a live-data adapter.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from nba_time_machine.api.read_models import (
    GameListResponse,
    MediaFeedResponse,
    full_game_from_projection,
    game_card_from_projection,
    media_item_from_projection,
    pregame_detail_from_projection,
    reason_from_projection,
    watchability_from_projection,
)
from nba_time_machine.spoilers.policy import (
    DisclosureLayer,
    GameContext,
    GameField,
    GameFieldName,
    MediaField,
    MediaFieldName,
    MediaItem,
    MediaSensitivity,
    project_game,
    project_general_media,
)

OUTPUT = Path(__file__).resolve().parents[2] / "frontend/src/fixtures/read-models.json"


def make_fixture_payloads() -> dict[str, object]:
    cursor = datetime(2026, 10, 8, 19, tzinfo=timezone.utc)
    tip = cursor + timedelta(hours=5)
    final = tip + timedelta(hours=3)
    game_id = UUID("11111111-1111-4111-8111-111111111111")
    sealed = GameContext(game_id=game_id, time_cursor=cursor, tip_at=tip, protection_ends_at=final)
    pregame_fields = (
        GameField(GameFieldName.HOME_TEAM, "Home", cursor, cursor),
        GameField(GameFieldName.AWAY_TEAM, "Away", cursor, cursor),
        GameField(GameFieldName.SCHEDULED_TIP, tip.isoformat(), cursor, cursor),
        GameField(GameFieldName.PREGAME_INTEREST, 6.0, cursor, cursor),
        GameField(GameFieldName.PREGAME_AVAILABILITY, "Probable", cursor, cursor),
    )
    full_fields = pregame_fields + (
        GameField(GameFieldName.WATCHABILITY_VERDICT, "Suggested", final, final),
        GameField(GameFieldName.WATCHABILITY_REASON, "Late run", final, final),
        GameField(GameFieldName.HOME_SCORE, 111, final, final),
        GameField(GameFieldName.AWAY_SCORE, 109, final, final),
        GameField(GameFieldName.RESULT, "Home won", final, final),
    )
    media = (
        MediaItem(
            "league-preview", cursor, cursor, MediaSensitivity.GENERAL,
            frozenset(), (
                MediaField(MediaFieldName.HEADLINE, "League preview", cursor, cursor),
                MediaField(MediaFieldName.EXCERPT, "Tonight's slate", cursor, cursor),
            ),
        ),
        MediaItem(
            "future-result", final, final, MediaSensitivity.OUTCOME_DEPENDENT,
            frozenset({game_id}), (
                MediaField(MediaFieldName.HEADLINE, "Postgame spoiler", final, final),
            ),
        ),
    )
    pregame = project_game(sealed, DisclosureLayer.PREGAME, full_fields)
    feed = project_general_media(media, time_cursor=cursor, games={game_id: sealed})
    watchability = project_game(sealed, DisclosureLayer.WATCHABILITY, full_fields)
    why = project_game(sealed, DisclosureLayer.WHY, full_fields)
    from dataclasses import replace
    full = project_game(replace(sealed, explicit_full_reveal=True), DisclosureLayer.FULL, full_fields)
    return {
        "games": GameListResponse(
            time_cursor=cursor, games=(game_card_from_projection(pregame, state="sealed"),),
        ).model_dump(mode="json"),
        "pregame_detail": pregame_detail_from_projection(pregame, state="sealed").model_dump(mode="json"),
        "watchability": watchability_from_projection(watchability).model_dump(mode="json"),
        "reason": reason_from_projection(why).model_dump(mode="json"),
        "full": full_game_from_projection(full).model_dump(mode="json"),
        "media": MediaFeedResponse(
            time_cursor=cursor,
            items=tuple(media_item_from_projection(item) for item in feed),
        ).model_dump(mode="json"),
    }


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(make_fixture_payloads(), indent=2, sort_keys=True) + "\n")
    print(OUTPUT)
