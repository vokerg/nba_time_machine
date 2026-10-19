"""Shared record-based expectation. No outcomes or player participation in its output."""
from typing import Literal
from pydantic import Field, BaseModel, ConfigDict, AwareDatetime
from datetime import datetime
from nba_time_machine.ranking.settings import Settings, clamp, ramp

VERSION = "pregame-records-v1"


class EnteringTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team: str
    wins: int | None = Field(default=None, ge=0, le=82)
    losses: int | None = Field(default=None, ge=0, le=82)
    smoothed_win_pct: float | None = Field(default=None, ge=0, le=1)


class StarPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    rank: int = Field(ge=1, le=100)
    slot_weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1)


class StarTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team: str
    normalized: float = Field(ge=0, le=1)
    players: list[StarPlayer] = Field(max_length=3)


class StarEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str
    observed_at: AwareDatetime
    available_at: AwareDatetime


class StarPotential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: float = Field(ge=0, le=10)
    overall_points: float = Field(ge=0, le=1.5)
    teams: list[StarTeam] = Field(min_length=2, max_length=2)
    evidence: list[StarEvidence] = Field(min_length=3, max_length=3)
    explanation: str


class PregameExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: Literal["pregame-records-v1", "pregame-context-v2"]
    rating: float = Field(ge=0, le=10)
    overall_points: float = Field(ge=0, le=3.5)
    coverage: Literal["records-only", "stars-only", "records-and-stars"]
    basis: Literal["reconstructed", "known-pre-tip", "mixed"]
    explanation: str
    missing: list[str]
    teams: list[EnteringTeam] = Field(min_length=2, max_length=2)
    sample_confidence: float | None = Field(default=None, ge=0, le=1)
    star_power: StarPotential | None = None
    formula: str
    source_ref: str
    observed_at: AwareDatetime
    available_at: AwareDatetime


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


def combine_expectation(records, stars):
    if stars is None:
        return records
    weight = 1.5 + (2 if records is not None else 0)
    points = stars['overall_points'] + (records['overall_points'] if records else 0)
    def stamp(value):
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    observed = max(stamp(e['observed_at']) for e in stars['evidence'])
    available = max(stamp(e['available_at']) for e in stars['evidence'])
    if records:
        observed, available = max(observed, stamp(records['observed_at'])), max(available, stamp(records['available_at']))
    return {
        'model':'pregame-context-v2', 'rating':round((stars['rating'] * 1.5 + (records['rating'] * 2 if records else 0)) / weight, 4), 'overall_points':round(points, 4),
        'coverage':'records-and-stars' if records else 'stars-only',
        'basis':'mixed' if records else 'known-pre-tip',
        'explanation': ('Entering team records and roster star potential. ' if records else 'Roster star potential; team record strength is unavailable. ') + stars['explanation'],
        'missing':['Confirmed star availability and lineups', 'Expected competitiveness', 'Rest and recent form', 'Rivalry and playoff stakes'] + ([] if records else ['Regular-season record strength']),
        'teams':records['teams'] if records else [{'team':t['team']} for t in stars['teams']],
        'sample_confidence':records['sample_confidence'] if records else None,
        'formula': ('Record component: ' + records['formula'] + ' ' if records else '') +
            'Star potential uses the existing rank curve, top three roster stars per team (weights 1, .4, .15), team normalization 1.55 and the shared two-team metric. Expectation = 10 × available component points / available maximum points. Postgame star credit uses actual minutes instead of roster potential; the two are not added together.',
        'source_ref': ';'.join(e['source_ref'] for e in stars['evidence']),
        'observed_at':observed, 'available_at':available, 'star_power':stars,
    }
