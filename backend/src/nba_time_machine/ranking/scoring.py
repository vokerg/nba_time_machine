"""Deterministic, provenance-carrying scoring; never an authorization boundary.

Caller must supply trusted normalized feature observations. Missing features are
omitted rather than imputed from current data. A historical as-of score must
not learn from observations obtained after that as-of moment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


class ScoreKind(str, Enum):
    PREGAME = "pregame"
    POSTGAME = "postgame"


class PregameSignal(str, Enum):
    TEAM_STRENGTH = "team_strength"
    EXPECTED_CLOSENESS = "expected_closeness"
    STANDINGS_LEVERAGE = "standings_leverage"
    STAR_AVAILABILITY = "star_availability"
    RECENT_FORM_REST = "recent_form_rest"
    RIVALRY = "rivalry"
    PLAYOFF_IMPLICATIONS = "playoff_implications"


class PostgameSignal(str, Enum):
    CLUTCH = "clutch"
    LEAD_CHANGES = "lead_changes"
    COMEBACK = "comeback"
    OVERTIME = "overtime"
    INDIVIDUAL_PERFORMANCE = "individual_performance"
    RARITY = "rarity"
    GAME_QUALITY = "game_quality"


PREGAME_VERSION = "pregame-v1"
POSTGAME_VERSION = "postgame-v1"
OVERALL_VERSION = "postgame-records-v2"
STAR_OVERALL_VERSION = "postgame-stars-v3"
POSTGAME_VERSIONS = (POSTGAME_VERSION, OVERALL_VERSION, STAR_OVERALL_VERSION)

PREGAME_WEIGHTS: Mapping[PregameSignal, int] = MappingProxyType({
    PregameSignal.TEAM_STRENGTH: 15,
    PregameSignal.EXPECTED_CLOSENESS: 25,
    PregameSignal.STANDINGS_LEVERAGE: 15,
    PregameSignal.STAR_AVAILABILITY: 15,
    PregameSignal.RECENT_FORM_REST: 10,
    PregameSignal.RIVALRY: 5,
    PregameSignal.PLAYOFF_IMPLICATIONS: 15,
})
POSTGAME_WEIGHTS: Mapping[PostgameSignal, int] = MappingProxyType({
    PostgameSignal.CLUTCH: 25,
    PostgameSignal.LEAD_CHANGES: 15,
    PostgameSignal.COMEBACK: 20,
    PostgameSignal.OVERTIME: 10,
    PostgameSignal.INDIVIDUAL_PERFORMANCE: 10,
    PostgameSignal.RARITY: 10,
    PostgameSignal.GAME_QUALITY: 10,
})


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    """Normalized 0..1 signal with independently inspectable source provenance."""

    value: float
    source_ref: str
    available_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if (type(self.value) not in (int, float)
                or not isfinite(float(self.value)) or not 0 <= self.value <= 1):
            raise ValueError("feature value must be a finite number in [0, 1]")
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("feature source_ref is required")
        _utc(self.available_at, "available_at")
        _utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    signal: str
    normalized_value: float
    weight: int
    weighted_contribution: float
    source_ref: str
    available_at: datetime
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedScore:
    game_id: UUID
    kind: ScoreKind
    model_version: str
    as_of: datetime
    value: float
    components: tuple[ScoreComponent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.game_id, UUID) or type(self.kind) is not ScoreKind:
            raise ValueError("score needs a canonical game UUID and score kind")
        if not isinstance(self.model_version, str) or not self.model_version:
            raise ValueError("model version is required")
        _utc(self.as_of, "as_of")
        if not isfinite(self.value) or not 0 <= self.value <= 10 or not self.components:
            raise ValueError("score must have finite 0..10 value and evidence")


def _calculate(
    game_id: UUID,
    *,
    kind: ScoreKind,
    version: str,
    signals: Mapping[Enum, FeatureObservation],
    weights: Mapping[Enum, int],
    as_of: datetime,
    tip_at: datetime | None,
    final_at: datetime | None,
) -> VersionedScore:
    cursor = _utc(as_of, "as_of")
    if not signals:
        raise ValueError("cannot score without observed features")
    if len(signals) > len(weights):
        raise ValueError("unexpected ranking features")
    tip = _utc(tip_at, "tip_at") if kind is ScoreKind.PREGAME and tip_at is not None else None
    final = _utc(final_at, "final_at") if kind is ScoreKind.POSTGAME and final_at is not None else None
    if kind is ScoreKind.PREGAME and tip is None:
        raise ValueError("pregame score requires trusted tip_at")
    if kind is ScoreKind.POSTGAME and (final is None or final > cursor):
        raise ValueError("postgame score requires a final no later than as_of")
    if kind is ScoreKind.PREGAME and cursor >= tip:
        # The scoring snapshot is explicitly taken before tipoff; do not silently
        # use later observations even when some old features look safe.
        raise ValueError("pregame scoring as_of must precede tipoff")

    total_weight = 0
    total = 0.0
    parts: list[ScoreComponent] = []
    for signal in sorted(signals, key=lambda item: str(item.value) if isinstance(item, Enum) else ""):
        if signal not in weights or type(signal) is not type(next(iter(weights))):
            raise ValueError("wrong feature family for score kind")
        observation = signals[signal]
        if type(observation) is not FeatureObservation:
            raise TypeError("ranking features must be FeatureObservation")
        available = _utc(observation.available_at, "available_at")
        observed = _utc(observation.observed_at, "observed_at")
        if available > cursor or observed > cursor:
            raise ValueError("ranking evidence cannot be newer than as_of")
        if tip is not None and (available >= tip or observed >= tip):
            raise ValueError("pregame evidence must predate tipoff")
        if final is not None and (available < final or observed < final):
            raise ValueError("postgame features must be observed no earlier than final")
        weight = weights[signal]
        total_weight += weight
        contribution = float(observation.value) * weight
        total += contribution
        parts.append(ScoreComponent(
            signal=signal.value, normalized_value=float(observation.value),
            weight=weight, weighted_contribution=round(contribution, 6),
            source_ref=observation.source_ref, available_at=available,
            observed_at=observed,
        ))
    return VersionedScore(
        game_id=game_id, kind=kind, model_version=version, as_of=cursor,
        value=round(10 * total / total_weight, 4),
        components=tuple(parts),
    )


def score_pregame(
    game_id: UUID,
    signals: Mapping[PregameSignal, FeatureObservation],
    *,
    tip_at: datetime,
    as_of: datetime,
) -> VersionedScore:
    return _calculate(
        game_id, kind=ScoreKind.PREGAME, version=PREGAME_VERSION,
        signals=signals, weights=PREGAME_WEIGHTS, tip_at=tip_at,
        final_at=None, as_of=as_of,
    )


def score_postgame(
    game_id: UUID,
    signals: Mapping[PostgameSignal, FeatureObservation],
    *,
    final_at: datetime,
    as_of: datetime,
) -> VersionedScore:
    return _calculate(
        game_id, kind=ScoreKind.POSTGAME, version=POSTGAME_VERSION,
        signals=signals, weights=POSTGAME_WEIGHTS, tip_at=None,
        final_at=final_at, as_of=as_of,
    )


def add_matchup_expectation(score, magnitude, *, source_ref, observed_at, available_at):
    """Keep legacy drama and add the shared 0..2 record-strength contribution."""
    if score.model_version != POSTGAME_VERSION or score.kind is not ScoreKind.POSTGAME or not score_evidence_is_consistent(score):
        raise ValueError("overall score needs consistent legacy postgame evidence")
    observation = FeatureObservation(magnitude, source_ref, available_at, observed_at)
    if max(observation.available_at, observation.observed_at) > score.as_of:
        raise ValueError("future matchup evidence")
    part = ScoreComponent("matchup_expectation", magnitude, 2, round(2 * magnitude, 6),
                          source_ref, available_at, observed_at)
    return VersionedScore(score.game_id, ScoreKind.POSTGAME, OVERALL_VERSION, score.as_of,
                          round(min(10, score.value + round(2 * magnitude, 4)), 4),
                          score.components + (part,))


def add_star_power(score, magnitude, *, source_ref, observed_at, available_at):
    if score.model_version not in (POSTGAME_VERSION, OVERALL_VERSION) or score.kind is not ScoreKind.POSTGAME or not score_evidence_is_consistent(score):
        raise ValueError("realized star power needs consistent postgame evidence")
    observation = FeatureObservation(magnitude, source_ref, available_at, observed_at)
    if max(observation.available_at, observation.observed_at) > score.as_of:
        raise ValueError("future star evidence")
    part = ScoreComponent("star_power", magnitude, 15, round(15 * magnitude, 6),
                          source_ref, available_at, observed_at)
    return VersionedScore(score.game_id, ScoreKind.POSTGAME, STAR_OVERALL_VERSION, score.as_of,
                          round(min(10, score.value + round(1.5 * magnitude, 4)), 4), score.components + (part,))


def component_points(score):
    """Fan-readable contributions, proportionally capped to reconcile to the total."""
    base = [p for p in score.components if p.signal not in ("matchup_expectation", "star_power")]
    denominator = sum(p.weight for p in base)
    points = [p.weighted_contribution if p.signal == "matchup_expectation"
              else p.weighted_contribution / 10 if p.signal == "star_power"
              else 10 * p.weighted_contribution / denominator for p in score.components]
    uncapped = sum(points)
    factor = score.value / uncapped if uncapped else 1
    return [round(p * factor, 4) for p in points]


def score_evidence_is_consistent(score: VersionedScore) -> bool:
    """Fail closed if a stored score no longer matches its evidence.

    This checks the *internal arithmetic and temporal shape* of a score, not
    whether its sources are independently trusted. Callers must still restrict
    the score family, profile cursor, and spoiler consent separately.
    """
    if type(score) is not VersionedScore:
        return False
    if score.model_version == STAR_OVERALL_VERSION:
        from dataclasses import replace
        if score.kind is not ScoreKind.POSTGAME or any(type(p) is not ScoreComponent
                or type(p.weight) is not int or p.weight <= 0
                or type(p.normalized_value) not in (int, float) or not isfinite(p.normalized_value)
                or not 0 <= p.normalized_value <= 1 for p in score.components):
            return False
        base = tuple(p for p in score.components if p.signal != "star_power")
        extra = tuple(p for p in score.components if p.signal == "star_power")
        drama = tuple(p for p in base if p.signal != "matchup_expectation")
        matchup = tuple(p for p in base if p.signal == "matchup_expectation")
        if not drama or len(extra) != 1 or len(matchup) > 1:
            return False
        value = round(10 * sum(p.normalized_value * p.weight for p in drama) / sum(p.weight for p in drama), 4)
        value = round(min(10, value + (round(2 * matchup[0].normalized_value, 4) if matchup else 0)), 4)
        try:
            underlying = replace(score, model_version=OVERALL_VERSION if matchup else POSTGAME_VERSION,
                                 value=value, components=base)
            if not score_evidence_is_consistent(underlying):
                return False
            rebuilt = add_star_power(underlying, extra[0].normalized_value, source_ref=extra[0].source_ref,
                                      observed_at=extra[0].observed_at, available_at=extra[0].available_at)
            return rebuilt == score
        except (ValueError, TypeError):
            return False
    if score.model_version == OVERALL_VERSION:
        if score.kind is not ScoreKind.POSTGAME:
            return False
        from dataclasses import replace
        if any(type(p) is not ScoreComponent or type(p.weight) is not int
               or p.weight <= 0 or type(p.normalized_value) not in (int, float)
               or not isfinite(p.normalized_value) or not 0 <= p.normalized_value <= 1
               for p in score.components):
            return False
        base = tuple(p for p in score.components if p.signal != "matchup_expectation")
        extra = tuple(p for p in score.components if p.signal == "matchup_expectation")
        if not base or len(extra) != 1:
            return False
        value = round(10 * sum(p.normalized_value * p.weight for p in base) / sum(p.weight for p in base), 4)
        legacy = replace(score, model_version=POSTGAME_VERSION, components=base, value=value)
        if not score_evidence_is_consistent(legacy):
            return False
        part = extra[0]
        try:
            rebuilt = add_matchup_expectation(legacy, part.normalized_value, source_ref=part.source_ref,
                                               observed_at=part.observed_at, available_at=part.available_at)
            return rebuilt == score
        except (ValueError, TypeError):
            return False
    if score.kind is ScoreKind.PREGAME:
        weights, version = PREGAME_WEIGHTS, PREGAME_VERSION
    elif score.kind is ScoreKind.POSTGAME:
        weights, version = POSTGAME_WEIGHTS, POSTGAME_VERSION
    else:
        return False
    if score.model_version != version or not 1 <= len(score.components) <= len(weights):
        return False
    if type(score.value) not in (int, float) or not isfinite(score.value):
        return False
    try:
        cursor = _utc(score.as_of, "as_of")
        by_name = {signal.value: weight for signal, weight in weights.items()}
        seen: set[str] = set()
        total = 0.0
        total_weight = 0
        for part in score.components:
            if type(part) is not ScoreComponent or type(part.signal) is not str:
                return False
            if part.signal not in by_name or part.signal in seen:
                return False
            seen.add(part.signal)
            if (type(part.normalized_value) not in (int, float)
                    or not isfinite(part.normalized_value)
                    or not 0 <= part.normalized_value <= 1
                    or type(part.weight) is not int
                    or part.weight != by_name[part.signal]
                    or type(part.weighted_contribution) not in (int, float)
                    or not isfinite(part.weighted_contribution)
                    or part.weighted_contribution != round(
                        part.normalized_value * part.weight, 6
                    )
                    or type(part.source_ref) is not str
                    or not part.source_ref.strip()
                    or _utc(part.available_at, "available_at") > cursor
                    or _utc(part.observed_at, "observed_at") > cursor):
                return False
            total += part.normalized_value * part.weight
            total_weight += part.weight
        return score.value == round(10 * total / total_weight, 4)
    except (TypeError, ValueError, OverflowError, AttributeError):
        return False
