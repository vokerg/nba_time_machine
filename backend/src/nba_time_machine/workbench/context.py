"""Inspectable matchup importance heuristics, not playoff outcome probabilities."""
from pydantic import Field

from nba_time_machine.ranking.settings import Settings, clamp, ramp


class ContextSettings(Settings):
    prior_games: float = Field(default=10, ge=0, le=82)
    minimum_games: int = Field(default=3, ge=1, le=82)
    confidence_games: float = Field(default=20, gt=0, le=82)
    win_pct_floor: float = Field(default=.5, ge=0, lt=1)
    win_pct_peak: float = Field(default=.75, gt=0, le=1)
    leader_rank_limit: float = Field(default=6, gt=1, le=15)
    close_games: float = Field(default=3, gt=0, le=20)
    boundary_games: float = Field(default=3, gt=0, le=20)
    late_games_floor: float = Field(default=50, ge=0, lt=82)
    late_games_peak: float = Field(default=78, gt=0, le=82)
    max_bonus: float = Field(default=2, ge=0, le=10)


# One implementation feeds pregame expectations and overall workbench ratings.
from nba_time_machine.ranking.pregame import RecordSettings, record_preview


def context_preview(context, settings):
    detail = {**context, "bonus": None, "calculation": None}
    if context["status"] != "available":
        return detail
    h, a = context["home"], context["away"]
    gp = min(h["games_played"], a["games_played"])
    if gp < settings.minimum_games:
        detail.update(status="insufficient_sample", reason="Too few prior games for the selected minimum; importance bonus is unavailable.")
        return detail
    smoothed = [(row["wins"] + settings.prior_games / 2) / (row["games_played"] + settings.prior_games) for row in (h, a)]
    strength = min(ramp(value, settings.win_pct_floor, settings.win_pct_peak) for value in smoothed)
    leaders = min(clamp((settings.leader_rank_limit - row["conference_rank"]) / (settings.leader_rank_limit - 1)) for row in (h, a))
    confidence = clamp(gp / settings.confidence_games)
    matchup = max(strength, leaders) * confidence
    same_conference = h["conference"] == a["conference"]
    gap = abs((h["wins"] - h["losses"]) - (a["wins"] - a["losses"])) / 2
    closeness = clamp(1 - gap / settings.close_games)
    late = ramp(gp, settings.late_games_floor, settings.late_games_peak)
    # Boundary proximity uses all teams sharing a win%-rank at/straddling 6 or
    # 10, rather than inventing an ordering for tied teams at a cutoff.
    boundary_rows = []
    if same_conference:
        conference = [r for r in context["standings"] if r["conference"] == h["conference"] and r["games_played"]]
        for cutoff in (6, 10):
            for row in conference:
                ties = sum(r["conference_rank"] == row["conference_rank"] for r in conference)
                if row["conference_rank"] <= cutoff < row["conference_rank"] + ties:
                    boundary_rows.append(row)
    boundary_gap = min((abs((row["wins"] - row["losses"]) - (boundary["wins"] - boundary["losses"])) / 2
        for row in (h, a) for boundary in boundary_rows), default=None)
    boundary = clamp(1 - boundary_gap / settings.boundary_games) if boundary_gap is not None else 0
    race = float(same_conference) * closeness * late * boundary
    magnitude = max(matchup, race)
    detail.update(bonus=round(settings.max_bonus * magnitude, 4), calculation={
        "home_smoothed_win_pct": smoothed[0], "away_smoothed_win_pct": smoothed[1],
        "strength_magnitude": strength, "leaders_magnitude": leaders,
        "sample_games": gp, "sample_confidence": confidence, "matchup_magnitude": matchup,
        "same_conference": same_conference, "games_gap": gap, "closeness": closeness,
        "late_season": late, "boundary_gap": boundary_gap, "boundary_proximity": boundary,
        "race_magnitude": race, "combined_magnitude": magnitude, "max_bonus": settings.max_bonus})
    return detail
