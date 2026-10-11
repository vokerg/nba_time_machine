"""Bridge versioned ranking evidence to existing deterministic spoiler fields.

The bridge never returns a raw postgame score as a projection. Actual disclosure
is always decided downstream by project_game with an explicit requested layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nba_time_machine.ranking.scoring import ScoreKind, VersionedScore
from nba_time_machine.spoilers.policy import GameField, GameFieldName


@dataclass(frozen=True, slots=True)
class VerdictBands:
    """Product-tunable thresholds; labels intentionally not fixed in scoring."""

    medium_from: float
    high_from: float
    low_label: str
    medium_label: str
    high_label: str

    def __post_init__(self) -> None:
        from math import isfinite
        if not (0 <= self.medium_from < self.high_from <= 10
                and isfinite(self.medium_from) and isfinite(self.high_from)):
            raise ValueError("verdict bands must be ordered within 0..10")
        if any(not isinstance(v, str) or not v.strip() for v in
               (self.low_label, self.medium_label, self.high_label)):
            raise ValueError("non-empty verdict labels are required")


def ranking_fields(
    score: VersionedScore, *,
    bands: VerdictBands | None = None,
    reason: str | None = None,
) -> tuple[GameField, ...]:
    """Construct only controlled field types with conservative component dates.

    A postgame reason must be separately requested through WHY. Never put raw
    component details, metrics or a numeric postgame score in a GameField.
    """
    if type(score) is not VersionedScore:
        raise TypeError("score must be a VersionedScore")
    available = max(part.available_at for part in score.components)
    observed = max(part.observed_at for part in score.components)
    if score.kind is ScoreKind.PREGAME:
        if bands is not None or reason is not None:
            raise ValueError("pregame interest does not take postgame disclosure settings")
        return (GameField(
            GameFieldName.PREGAME_INTEREST, score.value, available, observed,
        ),)
    if score.kind is not ScoreKind.POSTGAME or bands is None:
        raise ValueError("postgame scores require explicit coarse-verdict configuration")
    if score.value >= bands.high_from:
        label = bands.high_label
    elif score.value >= bands.medium_from:
        label = bands.medium_label
    else:
        label = bands.low_label
    fields = [GameField(GameFieldName.WATCHABILITY_VERDICT, label, available, observed)]
    if reason is not None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be meaningful")
        fields.append(GameField(GameFieldName.WATCHABILITY_REASON, reason, available, observed))
    return tuple(fields)
