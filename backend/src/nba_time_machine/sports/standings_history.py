"""Normalized daily result history; deliberately not a current standings feed."""
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nba_time_machine.sports.espn import competitors
from nba_time_machine.sports.morning_models import EASTERN, TEAM_NAMES, abbreviation, stamp

SEASON = "2025-2026"
START = date(2025, 10, 21)
END = date(2026, 4, 12)
FACT_TYPE = "provider_regular_season_day_v1"
SOURCE_ID = "espn-nba-games"
EAST = frozenset("ATL BOS BKN CHA CHI CLE DET IND MIA MIL NYK ORL PHI TOR WAS".split())
# Provider abbreviations are normalized by the shared morning contract.
CONFERENCES = {abbr: "East" if abbr in EAST else "West" for abbr in TEAM_NAMES}


def days(start: date, end: date):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    external_id: str = Field(pattern=r"^\d+$")
    tip: datetime
    home: str
    away: str
    home_score: int = Field(ge=0, le=300)
    away_score: int = Field(ge=0, le=300)

    @model_validator(mode="after")
    def consistent(self):
        if (self.home not in TEAM_NAMES or self.away not in TEAM_NAMES
                or self.home == self.away or self.home_score == self.away_score
                or self.tip.tzinfo is None or self.tip.utcoffset() is None):
            raise ValueError("invalid_regular_season_result")
        return self


class DayHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    season: str = SEASON
    day: date
    results: tuple[Result, ...] = ()
    errors: tuple[str, ...] = ()
    excluded: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if self.season != SEASON or not START <= self.day <= END:
            raise ValueError("unsupported_history_calendar")
        if (len(self.results) > 15
                or len({r.external_id for r in self.results}) != len(self.results)
                or len({t for r in self.results for t in (r.home, r.away)}) != 2 * len(self.results)
                or any(r.tip.astimezone(EASTERN).date() != self.day for r in self.results)):
            raise ValueError("inconsistent_daily_history")
        return self


def parse_day(payload: dict, day: date) -> DayHistory:
    """All-or-missing day coverage. No prose or provider standings are retained."""
    results, errors, excluded = [], [], 0
    if (not isinstance(payload.get("events"), list)
            or len(payload["events"]) > 20
            or payload.get("leagues", [{}])[0].get("abbreviation") != "NBA"
            or payload["leagues"][0].get("season", {}).get("year") != 2026):
        raise ValueError("unverified_scoreboard_day")
    for event in payload["events"]:
        try:
            if (type(event["season"]["year"]) is not int or event["season"]["year"] != 2026
                    or type(event["season"]["type"]) is not int or event["season"]["type"] not in (1, 2, 3)):
                raise ValueError("wrong_season")
            tip = stamp(event["date"])
            if tip.astimezone(EASTERN).date() != day:
                raise ValueError("wrong_nba_day")
            comp = event["competitions"][0]
            # ESPN marks Cup Championship with competition type 39 / CC even
            # when event.season.type is 2. It does not count in season records.
            if event["season"]["type"] != 2 or str(comp["type"]["id"]) == "39":
                excluded += 1
                continue
            status = event["status"]["type"]
            if status.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                excluded += 1
                continue
            if status["completed"] is not True:
                raise ValueError("unfinished_regular_season_game")
            teams = competitors(comp)
            def score(side):
                value = teams[side]["score"]
                if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).isdigit():
                    raise ValueError("invalid_score")
                return int(value)
            results.append(Result(external_id=str(event["id"]), tip=tip,
                home=abbreviation(teams["home"]["team"]["abbreviation"]),
                away=abbreviation(teams["away"]["team"]["abbreviation"]),
                home_score=score("home"), away_score=score("away")))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            errors.append("invalid_or_unfinished_regular_season_event")
    return DayHistory(day=day, results=tuple(results), errors=tuple(sorted(set(errors))), excluded=excluded)
