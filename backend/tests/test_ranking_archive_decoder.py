"""Fail-closed decoding of persisted JSON ranking component values (#10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from nba_time_machine.ranking.queries import _score_from_row
from nba_time_machine.ranking.repository import _components
from nba_time_machine.ranking.scoring import (
    FeatureObservation, PostgameSignal, score_postgame,
)


GAME = UUID("11111111-1111-4111-8111-111111111111")
FINAL = datetime(2026, 5, 6, 3, tzinfo=timezone.utc)
CURSOR = FINAL + timedelta(minutes=30)


def _valid_row() -> SimpleNamespace:
    score = score_postgame(
        GAME,
        {PostgameSignal.CLUTCH: FeatureObservation(
            1.0, "trusted:game-final", CURSOR, CURSOR,
        )},
        final_at=FINAL,
        as_of=CURSOR,
    )
    return SimpleNamespace(
        game_id=score.game_id,
        score_kind=score.kind.value,
        model_version=score.model_version,
        as_of=score.as_of,
        score_value=Decimal(str(score.value)),
        components=_components(score),
    )


@pytest.mark.parametrize(("field", "coercible_value"), [
    ("normalized_value", "1.0"),
    ("normalized_value", True),
    ("weight", "25"),
    ("weight", 25.9),
    ("weighted_contribution", "25.0"),
    ("weighted_contribution", "2.5e1"),
])
def test_rejects_malformed_json_numeric_types_before_coercion(
    field: str, coercible_value: object,
) -> None:
    row = _valid_row()
    assert _score_from_row(row) is not None
    # These would have passed the shared integrity check if the reader used
    # float()/int() coercion before validation.
    row.components[0][field] = coercible_value
    assert _score_from_row(row) is None


def test_accepts_genuine_json_numbers_including_integral_values() -> None:
    row = _valid_row()
    # JSON numbers may arrive as int or float; neither needs coercion.
    row.components[0]["normalized_value"] = 1
    row.components[0]["weighted_contribution"] = 25
    decoded = _score_from_row(row)
    assert decoded is not None
    assert decoded.game_id == GAME
    assert decoded.value == 10.0


def test_rejects_malformed_timestamps_without_throwing() -> None:
    row = _valid_row()
    row.components[0]["available_at"] = CURSOR.replace(tzinfo=None).isoformat()
    assert _score_from_row(row) is None
    row.components[0]["available_at"] = object()
    assert _score_from_row(row) is None
