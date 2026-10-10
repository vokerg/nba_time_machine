from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.spoilers import (
    DisclosureLayer, GameContext, GameField, GameFieldName,
    MediaField, MediaFieldName, MediaItem, MediaSensitivity,
    build_safe_ai_context, game_is_unsealed, order_game_cards,
    project_game, project_general_media,
)

UTC = timezone.utc
TIP = datetime(2026, 10, 8, 20, tzinfo=UTC)
CURSOR = TIP - timedelta(hours=1)
AFTER = TIP + timedelta(hours=3)


def game(*, cursor: datetime = CURSOR, acknowledged: bool = False, boundary: datetime | None = AFTER) -> GameContext:
    return GameContext(uuid4(), cursor, TIP, boundary, acknowledged)


def field(name: GameFieldName, value: str | int | float | None, at: datetime = CURSOR - timedelta(hours=1), observed: datetime | None = None) -> GameField:
    return GameField(name, value, at, observed if observed is not None else at)


def media_field(name: MediaFieldName, value: str | int, at: datetime = CURSOR) -> MediaField:
    return MediaField(name, value, at, at)


def item(item_id: str, sensitivity: MediaSensitivity, ids: frozenset, at: datetime, *attrs: MediaField) -> MediaItem:
    return MediaItem(item_id, at, at, sensitivity, ids, attrs)


def test_sealed_game_projects_only_proven_pregame_fields() -> None:
    context = game()
    attrs = (
        field(GameFieldName.HOME_TEAM, "Lakers"),
        field(GameFieldName.AWAY_TEAM, "Celtics"),
        field(GameFieldName.PREGAME_STANDINGS, "5-2"),
        field(GameFieldName.PREGAME_AVAILABILITY, "Questionable"),
        field(GameFieldName.PREGAME_INTEREST, 5.3),
        field(GameFieldName.HOME_SCORE, 124, AFTER),
        field(GameFieldName.IN_GAME_STATUS, "OT", AFTER),
        field(GameFieldName.RESULT, "Lakers won", AFTER),
        field(GameFieldName.HIGHLIGHT_THUMBNAIL, "gamewinner.jpg", AFTER),
        field(GameFieldName.HIGHLIGHT_RUNTIME_SECONDS, 3344, AFTER),
        field(GameFieldName.BOX_SCORE, "box", AFTER),
        field(GameFieldName.PREGAME_STANDINGS, "postgame 6-2", AFTER),
        field(GameFieldName.PREGAME_INTEREST, 99.0, CURSOR + timedelta(hours=2)),
    )
    projected = project_game(context, DisclosureLayer.PREGAME, attrs)
    assert projected.disclosure is DisclosureLayer.PREGAME
    assert projected.fields == {
        "home_team": "Lakers", "away_team": "Celtics",
        "pregame_standings": "5-2", "pregame_availability": "Questionable",
        "pregame_interest": 5.3,
    }
    # Merely requesting FULL does not accidentally bypass the explicit reveal gate.
    locked = project_game(context, DisclosureLayer.FULL, attrs)
    assert locked.disclosure is DisclosureLayer.PREGAME
    assert locked.fields == projected.fields


def test_verdict_why_and_explicit_full_are_distinct_actions() -> None:
    context = game()
    attrs = (
        field(GameFieldName.HOME_TEAM, "Lakers"),
        field(GameFieldName.WATCHABILITY_VERDICT, "Worth watching", AFTER),
        field(GameFieldName.WATCHABILITY_REASON, "Late comeback", AFTER),
        field(GameFieldName.RESULT, "Home win", AFTER),
        field(GameFieldName.HOME_SCORE, 113, AFTER),
        field(GameFieldName.HIGHLIGHT_RUNTIME_SECONDS, 3673, AFTER),
    )
    pregame = project_game(context, DisclosureLayer.PREGAME, attrs)
    verdict = project_game(context, DisclosureLayer.WATCHABILITY, attrs)
    why = project_game(context, DisclosureLayer.WHY, attrs)
    revealed = project_game(replace(context, explicit_full_reveal=True), DisclosureLayer.FULL, attrs)
    assert pregame.fields == {"home_team": "Lakers"}
    assert verdict.fields == {"home_team": "Lakers", "watchability_verdict": "Worth watching"}
    assert why.fields == {**verdict.fields, "watchability_reason": "Late comeback"}
    assert revealed.fields["result"] == "Home win"
    assert revealed.fields["highlight_runtime_seconds"] == 3673
    assert "postgame_quality_score" not in revealed.fields  # Never a default projected field.
    assert "home_score" not in verdict.fields
    # Revealed acknowledgement still honors lower requested disclosure layers.
    acknowledged = replace(context, acknowledged=True)
    assert project_game(acknowledged, DisclosureLayer.PREGAME, attrs).fields == pregame.fields
    assert project_game(acknowledged, DisclosureLayer.FULL, attrs).fields == revealed.fields


def test_timeline_boundary_inclusive_and_uncertain_boundary_sealed() -> None:
    context = game(cursor=AFTER - timedelta(microseconds=1))
    assert not game_is_unsealed(context)
    assert game_is_unsealed(replace(context, time_cursor=AFTER))
    assert game_is_unsealed(replace(context, time_cursor=AFTER.astimezone(timezone(timedelta(hours=4)))))
    assert not game_is_unsealed(replace(context, protection_ends_at=None))
    assert not game_is_unsealed(replace(context, protection_ends_at=TIP))
    assert not game_is_unsealed(replace(context, protection_ends_at=datetime(2026, 10, 8, 23)))
    assert not game_is_unsealed(replace(context, tip_at=None))
    assert game_is_unsealed(replace(context, acknowledged=True, protection_ends_at=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        game_is_unsealed(replace(context, time_cursor=datetime(2026, 10, 8, 23)))


def test_pregame_fields_fail_closed_on_ambiguous_or_late_history() -> None:
    context = game()
    attrs = (
        field(GameFieldName.HOME_TEAM, "safe"),
        field(GameFieldName.AWAY_TEAM, "later observation", CURSOR - timedelta(hours=1), AFTER),
        GameField(GameFieldName.PREGAME_AVAILABILITY, "unknown", None, CURSOR),
        field(GameFieldName.PREGAME_STANDINGS, "after tip", TIP),
        field(GameFieldName.PREGAME_INTEREST, 9.5, CURSOR, AFTER),
        field(GameFieldName.SCHEDULED_TIP, "unsafe", datetime(2026, 10, 8, 18)),
        field(GameFieldName.HOME_SCORE, 101, None),
    )
    assert project_game(context, DisclosureLayer.PREGAME, attrs).fields == {"home_team": "safe"}
    assert project_game(replace(context, acknowledged=True), DisclosureLayer.FULL, attrs).fields == {"home_team": "safe"}


def test_other_game_links_and_ambiguous_duplicate_values_are_dropped() -> None:
    context = game()
    attrs = (
        field(GameFieldName.HOME_TEAM, "A"),
        field(GameFieldName.HOME_TEAM, "B"),
        replace(field(GameFieldName.AWAY_TEAM, "Leaked other result"), related_game_ids=frozenset({uuid4()})),
        field(GameFieldName.PREGAME_INTEREST, 3.0),
    )
    assert project_game(context, DisclosureLayer.PREGAME, attrs).fields == {"pregame_interest": 3.0}


def test_media_feed_respects_cursor_even_when_game_is_acknowledged() -> None:
    a = game(acknowledged=True)
    b = game()
    known = frozenset({a.game_id})
    both = frozenset({a.game_id, b.game_id})
    items = (
        item("general", MediaSensitivity.GENERAL, frozenset(), CURSOR, media_field(MediaFieldName.HEADLINE, "League preview")),
        item("past-a", MediaSensitivity.OUTCOME_DEPENDENT, known, CURSOR, media_field(MediaFieldName.HEADLINE, "Game A result")),
        item("future-a", MediaSensitivity.OUTCOME_DEPENDENT, known, AFTER, media_field(MediaFieldName.HEADLINE, "Future spoiler", AFTER)),
        item("mixed", MediaSensitivity.OUTCOME_DEPENDENT, both, CURSOR, media_field(MediaFieldName.HEADLINE, "A and B results")),
        item("unlinked", MediaSensitivity.OUTCOME_DEPENDENT, frozenset(), CURSOR, media_field(MediaFieldName.HEADLINE, "Mystery result")),
        item("unknown", MediaSensitivity.UNKNOWN, known, CURSOR, media_field(MediaFieldName.HEADLINE, "No trustworthy label")),
        item("future-headline", MediaSensitivity.GENERAL, frozenset(), CURSOR, media_field(MediaFieldName.HEADLINE, "Future updated title", AFTER)),
        item("linked-general", MediaSensitivity.GENERAL, known, CURSOR, media_field(MediaFieldName.HEADLINE, "Misclassified")),
    )
    visible = project_general_media(items, time_cursor=CURSOR, games={a.game_id: a, b.game_id: b})
    assert [row.item_id for row in visible] == ["general", "past-a"]
    # Acknowledgement does not advance the general news/social/podcast universe.
    assert "Future spoiler" not in str(visible)


def test_media_pregame_and_indirect_image_runtime_spoilers() -> None:
    a = game()
    early = CURSOR - timedelta(hours=1)
    media = item(
        "preview", MediaSensitivity.PREGAME, frozenset({a.game_id}), early,
        media_field(MediaFieldName.HEADLINE, "Tonight's matchup", early),
        media_field(MediaFieldName.EXCERPT, "Tip at 8", early),
        media_field(MediaFieldName.THUMBNAIL_URL, "trophy-celebration.png", AFTER),
        media_field(MediaFieldName.RUNTIME_SECONDS, 3501, AFTER),
    )
    visible = project_general_media((media,), time_cursor=CURSOR, games={a.game_id: a})
    assert visible[0].fields == {"headline": "Tonight's matchup", "excerpt": "Tip at 8"}
    assert not project_general_media((replace(media, available_at=TIP),), time_cursor=AFTER, games={a.game_id: replace(a, time_cursor=AFTER)})
    assert not project_general_media((replace(media, observed_at=None),), time_cursor=CURSOR, games={a.game_id: a})
    assert not project_general_media((media,), time_cursor=CURSOR, games={})


def test_ai_context_and_card_order_consume_only_safe_projections() -> None:
    a, b = game(), game()
    a_card = project_game(a, DisclosureLayer.PREGAME, (
        field(GameFieldName.PREGAME_INTEREST, 2.0),
        field(GameFieldName.RESULT, "Huge upset", AFTER),
    ))
    b_card = project_game(b, DisclosureLayer.PREGAME, (
        field(GameFieldName.PREGAME_INTEREST, 7.0),
        field(GameFieldName.RESULT, "Boring", AFTER),
    ))
    ordered = order_game_cards((a_card, b_card))
    assert [c.game_id for c in ordered] == [b.game_id, a.game_id]
    context = build_safe_ai_context(ordered, ())
    assert "Huge upset" not in str(context)
    assert "Boring" not in str(context)
    assert "result" not in str(context)
    with pytest.raises(TypeError):
        build_safe_ai_context((a,), ())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        build_safe_ai_context((), (object(),))  # type: ignore[arg-type]


def test_invalid_request_and_untyped_field_are_not_accidental_permissions() -> None:
    context = game()
    with pytest.raises(ValueError, match="DisclosureLayer"):
        project_game(context, 99, ())  # type: ignore[arg-type]
    fake = GameField("home_team", "not a trusted enum", CURSOR, CURSOR)  # type: ignore[arg-type]
    assert project_game(context, DisclosureLayer.PREGAME, (fake,)).fields == {}


def test_ranking_invalid_numeric_signal_stably_falls_back() -> None:
    a, b = game(), game()
    bad = project_game(a, DisclosureLayer.PREGAME, (field(GameFieldName.PREGAME_INTEREST, 10**500),))
    missing = project_game(b, DisclosureLayer.PREGAME, ())
    assert [c.game_id for c in order_game_cards((bad, missing))] == sorted([a.game_id, b.game_id], key=str)
