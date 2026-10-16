"""Observed game evidence. None of these models is a spoiler-safe projection."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

EASTERN = ZoneInfo("America/New_York")
ALIASES = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA",
           "PHO": "PHX", "WSH": "WAS", "BRK": "BKN"}
CBS_ABBR = {"GSW": "GS", "NYK": "NY", "NOP": "NO", "SAS": "SA", "UTA": "UTA"}
TEAM_NAMES = dict(zip(
    "ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS".split(),
    ["Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls",
     "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons", "Golden State Warriors",
     "Houston Rockets", "Indiana Pacers", "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies",
     "Miami Heat", "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
     "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
     "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards"],
))


def abbreviation(value: str) -> str:
    result = ALIASES.get(value.upper(), value.upper())
    if result not in TEAM_NAMES:
        raise ValueError("unknown_nba_team")
    return result


def stamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive_source_timestamp")
    return parsed


def clock_ms(value: str) -> int:
    from decimal import Decimal, InvalidOperation
    try:
        parts = [Decimal(p) for p in value.split(":")]
    except (InvalidOperation, AttributeError):
        raise ValueError("invalid_clock") from None
    if len(parts) == 2:
        minute, second = parts
        if minute != int(minute) or not 0 <= second < 60:
            raise ValueError("invalid_clock")
        result = minute * 60 + second
    elif len(parts) == 1:
        result = parts[0]
    else:
        raise ValueError("invalid_clock")
    if not result.is_finite() or result < 0 or result * 1000 != int(result * 1000):
        raise ValueError("invalid_clock")
    return int(result * 1000)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeasonRecord(Model):
    wins: int = Field(ge=0, le=82, strict=True)
    losses: int = Field(ge=0, le=82, strict=True)

    @model_validator(mode="after")
    def valid_total(self):
        if self.wins + self.losses > 82:
            raise ValueError("invalid_season_record")
        return self


class MatchupRecords(Model):
    home_after: SeasonRecord
    away_after: SeasonRecord
    basis: Literal["espn_completed_game_total"] = "espn_completed_game_total"


class GameRef(Model):
    provider: Literal["espn", "cbs"]
    external_id: str = Field(min_length=1, max_length=64)
    day: date
    home: str
    away: str
    scheduled_at: AwareDatetime | None = None
    final: bool | None = None
    season_type: int | None = Field(default=None, strict=True)
    competition_type: str | None = Field(default=None, max_length=32)
    home_record: SeasonRecord | None = None
    away_record: SeasonRecord | None = None
    record_errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def matchup(self):
        if self.home not in TEAM_NAMES or self.away not in TEAM_NAMES or self.home == self.away:
            raise ValueError("invalid_matchup")
        if self.scheduled_at and self.scheduled_at.astimezone(EASTERN).date() != self.day:
            raise ValueError("wrong_nba_day")
        return self

    @property
    def key(self) -> tuple[date, str, str]:
        return self.day, self.home, self.away

    @property
    def cbs_abbr(self) -> str:
        return f"NBA_{self.day:%Y%m%d}_{CBS_ABBR.get(self.away, self.away)}@{CBS_ABBR.get(self.home, self.home)}"


class Team(Model):
    external_id: str = Field(min_length=1)
    abbreviation: str
    name: str
    score: int = Field(ge=0, strict=True)
    periods: tuple[int, ...]


class Play(Model):
    external_id: str | None = None
    index: int = Field(ge=0)
    source_sequence: str | None = None
    period: int = Field(ge=1, le=20, strict=True)
    remaining_ms: int = Field(ge=0, le=720000, strict=True)
    home: int = Field(ge=0, strict=True)
    away: int = Field(ge=0, strict=True)
    kind: str
    period_end: bool = False
    game_end: bool = False
    participant_ids: tuple[str, ...] = ()
    wallclock: AwareDatetime | None = None
    scoring: bool | None = None
    points: int | None = Field(default=None, ge=0, le=4, strict=True)


class PlayerBox(Model):
    external_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    starter: bool | None = None
    did_not_play: bool | None = None
    minutes: float | None = Field(default=None, ge=0, le=200)
    minutes_precision: Literal["rounded_minute", "second", "unknown"] = "unknown"
    statistics: dict[str, int] = Field(default_factory=dict)


class Evidence(Model):
    schema_version: Literal[1] = 1
    provider: Literal["espn", "cbs"]
    external_id: str = Field(min_length=1)
    ref: GameRef
    observed_at: AwareDatetime
    season: str
    game_type: Literal["preseason", "regular_season", "playoffs"]
    status: Literal["final", "pending"]
    home: Team
    away: Team
    plays: tuple[Play, ...] = ()
    players: tuple[PlayerBox, ...] = ()
    pbp_errors: tuple[str, ...] = ()
    box_errors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    source_end_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = None
    records: MatchupRecords | None = None
    record_errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def matchup(self):
        if (self.provider != self.ref.provider or self.home.external_id == self.away.external_id
                or self.home.abbreviation != self.ref.home or self.away.abbreviation != self.ref.away):
            raise ValueError("invalid_evidence_identity")
        return self

    @property
    def pbp_usable(self) -> bool:
        return self.status == "final" and bool(self.plays) and not self.pbp_errors

    @property
    def box_usable(self) -> bool:
        return self.status == "final" and bool(self.players) and not self.box_errors

    def retained_value(self) -> dict:
        # Capture timestamps must not turn identical daily observations into revisions.
        return self.model_dump(mode="json", exclude={"observed_at"})


def assess(evidence: Evidence) -> Evidence:
    """Check complete periods and totals without sorting, repairing or inventing plays."""
    pbp, box = set(evidence.pbp_errors), set(evidence.box_errors)
    h, a = evidence.home, evidence.away
    periods = len(h.periods)
    if (periods < 4 or periods != len(a.periods) or sum(h.periods) != h.score
            or sum(a.periods) != a.score):
        pbp.add("invalid_period_totals")
    if evidence.status != "final":
        pbp.add("not_final")
        box.add("not_final")
    if evidence.status == "final" and h.score == a.score:
        pbp.add("tied_final")
    plays = evidence.plays
    ids = [p.external_id for p in plays]
    if not plays:
        pbp.add("missing_plays")
    elif any(i is None for i in ids):
        pbp.add("missing_play_ids")
    elif len(set(ids)) != len(ids):
        pbp.add("duplicate_play_ids")
    if {p.period for p in plays} != set(range(1, periods + 1)):
        pbp.add("missing_or_extra_period")
    previous = (0, 0)
    end_scores = {}
    if plays and (plays[0].period != 1 or plays[0].remaining_ms != 720000
                  or (plays[0].home, plays[0].away) != (0, 0)):
        pbp.add("missing_initial_boundary")
    for i, play in enumerate(plays):
        if play.remaining_ms > (720000 if play.period <= 4 else 300000):
            pbp.add("invalid_period_clock")
        if i:
            prior = plays[i - 1]
            if (play.period < prior.period or
                    (play.period == prior.period and play.remaining_ms > prior.remaining_ms)):
                pbp.add("clock_order")
        delta = play.home - previous[0], play.away - previous[1]
        if min(delta) < 0:
            pbp.add("score_regression")
        if delta != (0, 0) and (sum(delta) not in (1, 2, 3) or min(delta) != 0):
            pbp.add("invalid_score_transition")
        if evidence.provider == "espn" and delta != (0, 0):
            if not play.scoring or play.points != sum(delta):
                pbp.add("scoring_event_mismatch")
        previous = play.home, play.away
        if play.period_end:
            if play.remaining_ms != 0 or play.period in end_scores:
                pbp.add("invalid_period_end")
            end_scores[play.period] = previous
    for period in range(1, periods + 1):
        if end_scores.get(period) != (sum(h.periods[:period]), sum(a.periods[:period])):
            pbp.add("period_end_mismatch")
        if period >= 4 and period < periods and sum(h.periods[:period]) != sum(a.periods[:period]):
            pbp.add("overtime_without_tie")
    if plays and (previous != (h.score, a.score) or not (plays[-1].period_end or plays[-1].game_end)):
        pbp.add("terminal_mismatch")
    if evidence.provider == "espn" and plays and not plays[-1].game_end:
        pbp.add("missing_game_end")
    player_ids = [p.external_id for p in evidence.players]
    if len(set(player_ids)) != len(player_ids):
        box.add("duplicate_player_ids")
    for team in (h, a):
        rows = [p for p in evidence.players if p.team_id == team.external_id]
        played = [p for p in rows if p.did_not_play is False]
        if not played:
            box.add("missing_team_players")
        if any(p.did_not_play is None or (p.did_not_play and p.statistics) for p in rows):
            box.add("unknown_participation")
        if any(p.minutes is None or "PTS" not in p.statistics for p in played):
            box.add("missing_player_minutes_or_points")
        required = {"PTS", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF",
                    "FGM", "FGA", "3PTM", "3PTA", "FTM", "FTA"}
        if any(not required.issubset(p.statistics) for p in played):
            box.add("missing_player_statistics")
        if sum(p.statistics.get("PTS", 0) for p in played) != team.score:
            box.add("player_point_totals_mismatch")
    if any(p.team_id not in (h.external_id, a.external_id) for p in evidence.players):
        box.add("wrong_player_team")
    if not box and any(i not in player_ids for p in plays for i in p.participant_ids):
        pbp.add("unresolved_participant")
    notes = evidence.notes + (("participant_box_match_unverified",) if box else ())
    return evidence.model_copy(update={"pbp_errors": tuple(sorted(pbp)), "box_errors": tuple(sorted(box)), "notes": notes})
