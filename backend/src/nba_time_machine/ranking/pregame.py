"""Shared record-based expectation. No outcomes or player participation in its output."""
from pydantic import Field
from nba_time_machine.workbench.enrichment import Settings, clamp, ramp

VERSION = "pregame-records-v1"


class RecordSettings(Settings):
    prior_games: float = Field(default=10, ge=0, le=82)
    minimum_games: int = Field(default=3, ge=1, le=82)
    confidence_games: float = Field(default=20, gt=0, le=82)
    win_pct_floor: float = Field(default=.5, ge=0, lt=1)
    win_pct_peak: float = Field(default=.75, gt=0, le=1)
    max_bonus: float = Field(default=2, ge=0, le=10)


def record_preview(context, settings):
    detail = {**context, "bonus": None, "calculation": None}
    if context["status"] != "available":
        return detail
    h, a = context["home"], context["away"]
    gp = min(h["games_played"], a["games_played"])
    if gp < settings.minimum_games:
        return {**detail, "status": "insufficient_sample", "reason": "Too few earlier games for the selected minimum; importance bonus unavailable."}
    smoothed = [(r["wins"] + settings.prior_games/2)/(r["games_played"] + settings.prior_games) for r in (h,a)]
    strengths = [ramp(v, settings.win_pct_floor, settings.win_pct_peak) for v in smoothed]
    confidence = clamp(gp/settings.confidence_games)
    magnitude = min(strengths) * confidence
    return {**detail, "bonus": round(settings.max_bonus*magnitude, 4), "calculation": {
        "home_smoothed_win_pct": smoothed[0], "away_smoothed_win_pct": smoothed[1],
        "home_strength_magnitude": strengths[0], "away_strength_magnitude": strengths[1],
        "strength_magnitude": min(strengths), "sample_games": gp, "sample_confidence": confidence,
        "matchup_magnitude": magnitude, "combined_magnitude": magnitude, "max_bonus": settings.max_bonus}}


def expectation(context, *, source_ref, observed_at, available_at):
    """Explicit allowlist: never serialize source records after the game or subtraction."""
    measured = record_preview(context, RecordSettings())
    if measured["bonus"] is None:
        return None
    calc = measured["calculation"]
    return {
        "model": VERSION, "rating": round(10 * calc["matchup_magnitude"], 4),
        "overall_points": measured["bonus"], "coverage": "records-only",
        "basis": "reconstructed",
        "explanation": "Both teams' entering win rates, smoothed toward .500; the weaker team and the smaller sample limit the matchup strength. This is not a win probability.",
        "missing": ["Expected lineups and injuries", "Expected competitiveness", "Rest and recent form", "Rivalry and playoff stakes"],
        "teams": [{"team": context[side]["team"], "wins": context[side]["wins"],
                   "losses": context[side]["losses"], "smoothed_win_pct": calc[side + "_smoothed_win_pct"]}
                  for side in ("home", "away")],
        "sample_confidence": calc["sample_confidence"],
        "formula": "10 × min(team strengths) × min(earlier games / 20, 1); strength = clamp(((wins + 5) / (games + 10) − .50) / .25, 0, 1). Overall bonus = expectation / 5, capped with the total at 10.",
        "source_ref": source_ref, "observed_at": observed_at, "available_at": available_at,
    }
