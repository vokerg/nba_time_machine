"""Explicit, uncalibrated preview formulas for measured performances and patterns."""
from pydantic import Field

from nba_time_machine.ranking.entertainment_features import EntertainmentMeasurements


from nba_time_machine.ranking.settings import Settings, clamp, ramp


class PlayerSettings(Settings):
    points_floor: float = Field(default=25, ge=0, le=200)
    points_peak: float = Field(default=60, gt=0, le=250)
    assists_floor: float = Field(default=8, ge=0, le=100)
    assists_peak: float = Field(default=20, gt=0, le=150)
    rebounds_floor: float = Field(default=12, ge=0, le=150)
    rebounds_peak: float = Field(default=30, gt=0, le=200)
    stocks_floor: float = Field(default=4, ge=0, le=100)
    stocks_peak: float = Field(default=12, gt=0, le=150)
    efficiency_floor: float = Field(default=.50, ge=0, le=2)
    efficiency_peak: float = Field(default=.75, gt=0, le=3)
    secondary_weight: float = Field(default=.15, ge=0, le=1)
    efficiency_weight: float = Field(default=.1, ge=0, le=1)
    triple_double_weight: float = Field(default=.1, ge=0, le=1)
    turnover_penalty: float = Field(default=.1, ge=0, le=1)
    turnover_scale: float = Field(default=10, gt=0, le=100)
    runner_up_weight: float = Field(default=.25, ge=0, le=1)
    max_bonus: float = Field(default=4, ge=0, le=10)


class PatternSettings(Settings):
    max_lead_floor: float = Field(default=20, ge=0, le=200)
    max_lead_peak: float = Field(default=60, gt=0, le=250)
    first_half_lead_floor: float = Field(default=15, ge=0, le=200)
    first_half_lead_peak: float = Field(default=40, gt=0, le=250)
    quarter_margin_floor: float = Field(default=20, ge=0, le=200)
    quarter_margin_peak: float = Field(default=40, gt=0, le=250)
    low_quarter_ceiling: float = Field(default=15, gt=0, le=50)
    high_quarter_floor: float = Field(default=35, ge=0, le=150)
    high_quarter_peak: float = Field(default=55, gt=0, le=200)
    scoring_drought_floor: float = Field(default=240000, ge=0, le=7200000)
    scoring_drought_peak: float = Field(default=720000, gt=0, le=10800000)
    second_group_weight: float = Field(default=.2, ge=0, le=1)
    max_bonus: float = Field(default=3, ge=0, le=10)


def player_assessment(row, config: PlayerSettings):
    s = row["statistics"]
    axes = []
    for key, raw in (("points", s["PTS"]), ("assists", s["AST"]),
                     ("rebounds", s["REB"]), ("stocks", s["STL"] + s["BLK"])):
        floor, peak = getattr(config, key + "_floor"), getattr(config, key + "_peak")
        axes.append({"signal": key, "raw": raw, "floor": floor, "peak": peak,
                     "normalized": ramp(raw, floor, peak)})
    ordered = sorted(axes, key=lambda a: -a["normalized"])
    peak = ordered[0]["normalized"]
    secondary = sum(a["normalized"] for a in ordered[1:3]) * config.secondary_weight
    efficiency = (ramp(row["true_shooting"], config.efficiency_floor, config.efficiency_peak)
                  if row["true_shooting"] is not None else None)
    efficiency_bonus = axes[0]["normalized"] * (efficiency or 0) * config.efficiency_weight
    triple = config.triple_double_weight if row["double_digit_categories"] >= 3 else 0
    turnover = clamp(s["TO"] / config.turnover_scale) * config.turnover_penalty
    raw_total = peak + secondary + efficiency_bonus + triple - turnover
    return {**row, "axes": axes, "efficiency_normalized": efficiency,
        "terms": {"strongest_axis": peak, "secondary_axes": secondary,
                  "efficiency_bonus": efficiency_bonus, "triple_double_bonus": triple,
                  "turnover_penalty": -turnover},
        "before_clamp": raw_total, "severity": clamp(raw_total)}


def enrichment_preview(measurements: EntertainmentMeasurements, player: PlayerSettings,
                       pattern: PatternSettings) -> dict:
    players = None
    player_bonus = None
    if measurements.players is not None:
        players = sorted((player_assessment(row, player) for row in measurements.players),
                         key=lambda row: (-row["severity"], -row["statistics"]["PTS"],
                                          -row["statistics"]["AST"], -row["statistics"]["REB"], row["player_id"]))
        first = players[0]["severity"] if players else 0
        second = players[1]["severity"] if len(players) > 1 else 0
        normalized = clamp(first + player.runner_up_weight * second)
        player_bonus = {"strongest": first, "runner_up": second,
            "runner_up_weight": player.runner_up_weight, "normalized": normalized,
            "cap": player.max_bonus, "points": player.max_bonus * normalized,
            "player_ids": [p["player_id"] for p in players[:2]]}
    patterns = None
    pattern_bonus = None
    if measurements.patterns is not None:
        patterns = []
        for row in measurements.patterns:
            signal = row["signal"]
            if signal == "low_quarter":
                floor, peak = pattern.low_quarter_ceiling, 0
                value = clamp((floor - row["raw"]) / floor)
            else:
                floor, peak = getattr(pattern, signal + "_floor"), getattr(pattern, signal + "_peak")
                value = ramp(row["raw"], floor, peak)
            group = "dominance" if signal in ("max_lead", "first_half_lead", "quarter_margin") else "scoring_extremes"
            patterns.append({**row, "floor": floor, "peak": peak, "normalized": value, "group": group})
        groups = {group: max(row["normalized"] for row in patterns if row["group"] == group)
                  for group in ("dominance", "scoring_extremes")}
        strongest, other = sorted(groups.values(), reverse=True)
        normalized = clamp(strongest + pattern.second_group_weight * other)
        pattern_bonus = {"groups": groups, "strongest_group": strongest, "second_group": other,
            "second_group_weight": pattern.second_group_weight, "normalized": normalized,
            "cap": pattern.max_bonus, "points": pattern.max_bonus * normalized}
    return {"measurement_version": measurements.version, "players": players, "patterns": patterns,
        "player_errors": list(measurements.player_errors), "pattern_errors": list(measurements.pattern_errors),
        "player_bonus": player_bonus, "pattern_bonus": pattern_bonus,
        "historical_rarity": None,
        "rarity_status": "Extremity heuristics only; no historical percentile dataset."}
