"""Preview-only configurations; never accepted by production scoring or archival."""
from dataclasses import asdict
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nba_time_machine.ranking.morning_features import TrajectoryFeatures
from nba_time_machine.ranking.entertainment_features import EntertainmentMeasurements
from nba_time_machine.workbench.enrichment import PlayerSettings, PatternSettings, enrichment_preview
from nba_time_machine.workbench.context import ContextSettings, RecordSettings, context_preview, record_preview

SIGNALS = {
    "clutch": ("Clutch time", "clutch_ms", "milliseconds"),
    "lead_changes": ("Lead changes", "lead_changes", "changes"),
    "comeback": ("Winner's largest deficit", "winner_max_deficit", "points"),
    "overtime": ("Overtime", "overtime_periods", "periods"),
}
MISSING = [
    {"signal": "star_power", "label": "Star power / star availability", "reason": "No trusted player-strength or historical availability features are produced."},
    {"signal": "stakes", "label": "Stakes / leaders facing each other", "reason": "No as-of team strength, standings leverage, seeding or playoff context is produced."},
    {"signal": "rivalry", "label": "Rivalry / history", "reason": "No rivalry feature producer is connected."},
    {"signal": "recent_form_rest", "label": "Recent form / rest", "reason": "No historically valid form or rest features are produced."},
    {"signal": "expected_closeness", "label": "Expected closeness", "reason": "No pre-tip prediction inputs are connected; observed clutch is a separate postgame measurement."},
    {"signal": "rarity", "label": "Historical rarity", "reason": "No historical-baseline feature is produced."},
    {"signal": "game_quality", "label": "Tactical / subjective game quality", "reason": "No trusted quality feature is produced."},
]


class TuningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    schema_version: Literal[1, 2, 3, 4] = 1
    version: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    weights: dict[str, float]
    scales: dict[str, float]
    medium_from: float = Field(ge=0, le=10)
    high_from: float = Field(ge=0, le=10)
    player: PlayerSettings | None = None
    pattern: PatternSettings | None = None
    context: ContextSettings | None = None
    importance: RecordSettings | None = None

    @model_validator(mode="after")
    def valid_config(self):
        if self.schema_version >= 2 and (self.player is None or self.pattern is None):
            raise ValueError("enriched formulas require explicit player and pattern settings")
        if (self.schema_version == 3) != (self.context is not None):
            raise ValueError("only v3 requires explicit context settings")
        if (self.schema_version == 4) != (self.importance is not None):
            raise ValueError("only v4 requires explicit game-record importance settings")
        if self.schema_version == 1 and (self.player is not None or self.pattern is not None):
            raise ValueError("v1 cannot carry enrichment settings")
        if set(self.weights) != set(SIGNALS) or set(self.scales) != set(SIGNALS):
            raise ValueError("configuration must contain exactly the four supported signals")
        if any(not isfinite(v) or not 0 <= v <= 1000 for v in self.weights.values()):
            raise ValueError("weights must be finite numbers between 0 and 1000")
        if not sum(self.weights.values()):
            raise ValueError("at least one weight must be positive")
        if any(not isfinite(v) or not 0 < v <= 1_000_000_000 for v in self.scales.values()):
            raise ValueError("normalization scales must be positive finite numbers")
        if self.medium_from >= self.high_from:
            raise ValueError("verdict thresholds must be ordered")
        return self


def preview(metrics: TrajectoryFeatures, config: TuningConfig) -> dict:
    raw = asdict(metrics)
    denominator = sum(config.weights.values())
    parts = []
    total = 0.0
    for signal, (label, field, unit) in SIGNALS.items():
        value = min(raw[field] / config.scales[signal], 1)
        weight = config.weights[signal]
        total += value * weight
        parts.append({"signal": signal, "label": label, "raw": raw[field], "unit": unit,
            "scale": config.scales[signal], "normalized": value, "weight": weight,
            "effective_weight_percent": 100 * weight / denominator,
            "score_contribution": 10 * value * weight / denominator})
    value = round(10 * total / denominator, 4)
    verdict = ("Worth watching" if value >= config.high_from else
               "Worth considering" if value >= config.medium_from else "Lower priority")
    return {"version": config.version, "score": value, "verdict": verdict,
            "weight_denominator": denominator, "signals": parts}


def candidate_preview(metrics: TrajectoryFeatures, measurements: EntertainmentMeasurements,
                      config: TuningConfig, context: dict | None = None) -> dict:
    base = preview(metrics, config)
    if config.schema_version == 1:
        return base
    details = enrichment_preview(measurements, config.player, config.pattern)
    # No dilution of a rare performance by unrelated zero-valued drama signals.
    # Missing box evidence yields an explicitly partial preview with no invented
    # player term; no production score is written from this development model.
    player = details["player_bonus"]["points"] if details["player_bonus"] is not None else None
    pattern = details["pattern_bonus"]["points"] if details["pattern_bonus"] is not None else None
    importance = context_preview(context, config.context) if config.schema_version == 3 and context is not None else None
    if config.schema_version == 4 and context is not None:
        importance = record_preview(context, config.importance)
    context_bonus = importance["bonus"] if importance is not None else None
    uncapped = base["score"] + sum(v for v in (player, pattern, context_bonus) if v is not None)
    capped = min(10, uncapped)
    value = round(capped, 4)
    verdict = ("Worth watching" if value >= config.high_from else
               "Worth considering" if value >= config.medium_from else "Lower priority")
    missing = ([] if player is not None else ["player performance"]) + ([] if pattern is not None else ["extreme patterns"])
    if config.schema_version >= 3 and context_bonus is None:
        missing.append("game importance")
    return {**base, "score": value, "verdict": verdict, "drama_score": base["score"],
        "player_bonus": player, "pattern_bonus": pattern, "before_cap": uncapped,
        "cap_adjustment": capped - uncapped, "rounding_adjustment": value - capped,
        **({"context_bonus": context_bonus, "context": importance} if config.schema_version >= 3 else {}),
        "coverage": "partial" if missing else "complete", "missing_families": missing,
        "enrichment": details}
