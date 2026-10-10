from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from nba_time_machine.api.read_models import (
    FullGameResponse,
    GameCardResponse,
    GameListResponse,
    MediaFeedResponse,
    PregameDetailResponse,
    full_game_from_projection,
    game_card_from_projection,
    media_item_from_projection,
    pregame_detail_from_projection,
    reason_from_projection,
    watchability_from_projection,
)
from nba_time_machine.spoilers.policy import (
    DisclosureLayer, GameContext, GameField, GameFieldName, GameProjection,
    MediaField, MediaFieldName, MediaItem, MediaProjection, MediaSensitivity,
    project_game, project_general_media,
)

CURSOR = datetime(2026, 10, 8, 19, tzinfo=timezone.utc)
TIP = CURSOR + timedelta(hours=5)
FINAL = TIP + timedelta(hours=3)
GAME_ID = UUID("11111111-1111-4111-8111-111111111111")


def game(*, full: bool = False, acknowledged: bool = False) -> GameContext:
    return GameContext(
        GAME_ID, CURSOR, TIP, FINAL, acknowledged=acknowledged,
        explicit_full_reveal=full,
    )


def fact(name: GameFieldName, value: str | int | float, when: datetime = CURSOR) -> GameField:
    return GameField(name, value, when, when)


def facts() -> tuple[GameField, ...]:
    return (
        fact(GameFieldName.HOME_TEAM, "Home"),
        fact(GameFieldName.AWAY_TEAM, "Away"),
        fact(GameFieldName.SCHEDULED_TIP, TIP.isoformat()),
        fact(GameFieldName.PREGAME_STANDINGS, "4-2"),
        fact(GameFieldName.PREGAME_AVAILABILITY, "Probable"),
        fact(GameFieldName.PREGAME_INTEREST, 5.5),
        fact(GameFieldName.WATCHABILITY_VERDICT, "Strong", FINAL),
        fact(GameFieldName.WATCHABILITY_REASON, "Late surge", FINAL),
        fact(GameFieldName.HOME_SCORE, 115, FINAL),
        fact(GameFieldName.AWAY_SCORE, 112, FINAL),
        fact(GameFieldName.RESULT, "Home won", FINAL),
        fact(GameFieldName.HIGHLIGHT_THUMBNAIL, "victory.jpg", FINAL),
        fact(GameFieldName.HIGHLIGHT_RUNTIME_SECONDS, 3555, FINAL),
    )


def wire(value: object) -> dict[str, object]:
    return json.loads(value.model_dump_json())  # type: ignore[attr-defined]


def test_sealed_card_and_pregame_detail_omit_result_and_nullable_keys() -> None:
    projection = project_game(game(), DisclosureLayer.PREGAME, facts())
    card = game_card_from_projection(projection, state="sealed")
    detail = pregame_detail_from_projection(projection, state="sealed")
    assert isinstance(card, GameCardResponse)
    assert isinstance(detail, PregameDetailResponse)
    assert card.model_dump()["home_team"] == "Home"
    assert "pregame_standings" not in wire(card)
    assert wire(detail)["pregame_standings"] == "4-2"
    for response in (card, detail):
        payload = wire(response)
        assert payload["disclosure"] == "pregame"
        assert payload["state"] == "sealed"
        assert set(payload).isdisjoint({
            "home_score", "away_score", "result", "box_score",
            "highlight_thumbnail", "highlight_runtime_seconds",
            "watchability_verdict", "postgame_quality_score",
        })

    empty = game_card_from_projection(
        project_game(game(), DisclosureLayer.PREGAME, ()), state="sealed",
    )
    assert set(wire(empty)) == {"game_id", "state", "disclosure"}


def test_verdict_reason_and_full_reveal_have_separate_shapes() -> None:
    verdict = project_game(game(), DisclosureLayer.WATCHABILITY, facts())
    why = project_game(game(), DisclosureLayer.WHY, facts())
    blocked_full = project_game(game(), DisclosureLayer.FULL, facts())
    allowed_full = project_game(game(full=True), DisclosureLayer.FULL, facts())

    assert blocked_full.disclosure is DisclosureLayer.PREGAME
    with pytest.raises(ValueError, match="expected policy disclosure FULL"):
        full_game_from_projection(blocked_full)

    verdict_payload = wire(watchability_from_projection(verdict))
    why_payload = wire(reason_from_projection(why))
    full_payload = wire(full_game_from_projection(allowed_full))
    assert verdict_payload == {
        "game_id": str(GAME_ID), "disclosure": "watchability",
        "watchability_verdict": "Strong",
    }
    assert why_payload["watchability_reason"] == "Late surge"
    assert "watchability_reason" not in verdict_payload
    for payload in (verdict_payload, why_payload):
        assert "home_score" not in payload
        assert "away_score" not in payload
        assert "postgame_quality_score" not in payload
    assert full_payload["home_score"] == 115
    assert full_payload["highlight_runtime_seconds"] == 3555
    assert full_payload["disclosure"] == "full"
    assert "postgame_quality_score" not in full_payload


def test_malicious_projection_fields_and_direct_model_extras_are_rejected() -> None:
    safe = project_game(game(), DisclosureLayer.PREGAME, facts())
    poisoned = replace(safe, fields={**safe.fields, "home_score": 999})
    with pytest.raises(ValueError, match="unexpected fields"):
        game_card_from_projection(poisoned, state="sealed")
    with pytest.raises(ValueError, match="unexpected fields"):
        pregame_detail_from_projection(poisoned, state="sealed")
    with pytest.raises(ValidationError):
        GameCardResponse(game_id=GAME_ID, state="sealed", home_score=999)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        FullGameResponse(game_id=GAME_ID, postgame_quality_score=9.9)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        GameCardResponse(game_id=GAME_ID, state="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        GameCardResponse(game_id=GAME_ID, state="sealed", pregame_interest=float("nan"))
    with pytest.raises(TypeError):
        game_card_from_projection(object(), state="sealed")  # type: ignore[arg-type]


def test_global_media_feed_never_uses_single_game_acknowledgement_as_time_override() -> None:
    acknowledged = game(acknowledged=True)
    media = (
        MediaItem(
            "preview", CURSOR, CURSOR, MediaSensitivity.PREGAME,
            frozenset({GAME_ID}),
            (
                MediaField(MediaFieldName.HEADLINE, "Pregame story", CURSOR, CURSOR),
                MediaField(MediaFieldName.EXCERPT, "Matchup", CURSOR, CURSOR),
                MediaField(MediaFieldName.THUMBNAIL_URL, "future-winner.jpg", FINAL, FINAL),
                MediaField(MediaFieldName.RUNTIME_SECONDS, 3700, FINAL, FINAL),
            ),
        ),
        MediaItem(
            "after", FINAL, FINAL, MediaSensitivity.OUTCOME_DEPENDENT,
            frozenset({GAME_ID}),
            (MediaField(MediaFieldName.HEADLINE, "Final result", FINAL, FINAL),),
        ),
    )
    projected = project_general_media(media, time_cursor=CURSOR, games={GAME_ID: acknowledged})
    items = tuple(media_item_from_projection(item) for item in projected)
    response = MediaFeedResponse(time_cursor=CURSOR, items=items)
    payload = wire(response)
    assert len(payload["items"]) == 1
    assert payload["items"][0] == {
        "item_id": "preview", "headline": "Pregame story", "excerpt": "Matchup",
    }
    assert "future-winner.jpg" not in response.model_dump_json()


def test_media_rejects_untrusted_fields_and_missing_headline() -> None:
    with pytest.raises(ValueError, match="unexpected fields"):
        media_item_from_projection(MediaProjection("m", {"headline": "OK", "final_score": "100-90"}))
    with pytest.raises(ValidationError):
        media_item_from_projection(MediaProjection("m", {"excerpt": "No headline"}))


def test_composable_game_list_and_cursor_serialization() -> None:
    card = game_card_from_projection(
        project_game(game(), DisclosureLayer.PREGAME, facts()), state="sealed",
    )
    offset_cursor = CURSOR.astimezone(timezone(timedelta(hours=4)))
    payload = wire(GameListResponse(time_cursor=offset_cursor, games=(card,)))
    assert payload["time_cursor"] == "2026-10-08T19:00:00Z"
    assert payload["games"][0]["game_id"] == str(GAME_ID)
    with pytest.raises(ValidationError, match="timezone-aware"):
        GameListResponse(time_cursor=datetime(2026, 10, 8, 19), games=(card,))


def test_checked_in_frontend_fixture_is_generated_from_contracts() -> None:
    from pathlib import Path
    from runpy import run_path

    backend = Path(__file__).resolve().parents[1]
    generated = run_path(str(backend / "scripts/export_read_model_fixtures.py"))[
        "make_fixture_payloads"
    ]()
    checked_in = json.loads(
        (backend.parent / "frontend/src/fixtures/read-models.json").read_text()
    )
    assert generated == checked_in
    assert "Postgame spoiler" not in json.dumps(generated)
