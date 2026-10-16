"""Parse the observed ESPN scoreboard/summary interfaces, never source prose."""
from __future__ import annotations

from datetime import date, datetime
import re

from nba_time_machine.sports.morning_models import (
    EASTERN, TEAM_NAMES, Evidence, GameRef, Play, PlayerBox, Team, abbreviation,
    assess, clock_ms, stamp, SeasonRecord, MatchupRecords,
)


def total_record(row: dict, field: str) -> SeasonRecord:
    values = [r for r in row[field] if r.get("type") == "total"]
    if len(values) != 1 or not isinstance(values[0].get("summary"), str):
        raise ValueError("missing_or_ambiguous_total_record")
    text = values[0]["summary"]
    if re.fullmatch(r"\d{1,2}-\d{1,2}", text) is None or values[0].get("displayValue", text) != text:
        raise ValueError("invalid_total_record")
    wins, losses = map(int, text.split("-"))
    return SeasonRecord(wins=wins, losses=losses)


def competitors(competition: dict) -> dict:
    rows = competition["competitors"]
    if len(rows) != 2 or {r["homeAway"] for r in rows} != {"home", "away"}:
        raise ValueError("invalid_competitors")
    return {r["homeAway"]: r for r in rows}


def scoreboard(payload: dict, day: date) -> list[GameRef]:
    result = []
    for event in payload["events"]:
        if not str(event["id"]).isdigit():
            raise ValueError("invalid_espn_id")
        comp = event["competitions"][0]
        teams = competitors(comp)
        tip = stamp(event["date"])
        if tip.astimezone(EASTERN).date() != day:
            raise ValueError("scoreboard_wrong_day")
        records, record_errors = {}, []
        for side in ("home", "away"):
            try:
                records[side + "_record"] = total_record(teams[side], "records")
            except (ValueError, KeyError, TypeError, AttributeError):
                record_errors.append("invalid_or_missing_scoreboard_" + side + "_record")
        result.append(GameRef(provider="espn", external_id=str(event["id"]), day=day,
            home=abbreviation(teams["home"]["team"]["abbreviation"]),
            away=abbreviation(teams["away"]["team"]["abbreviation"]),
            scheduled_at=tip, final=event["status"]["type"]["completed"],
            season_type=event.get("season", {}).get("type"),
            competition_type=str(comp["type"]["id"]) if comp.get("type", {}).get("id") is not None else None,
            record_errors=tuple(record_errors), **records))
    if len({r.key for r in result}) != len(result):
        raise ValueError("duplicate_matchups")
    return result


def parse_statistics(values: dict[str, str]) -> dict[str, int]:
    result = {}
    for key in ("PTS", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"):
        if key in values:
            text = str(values[key])
            if not text.lstrip("+-").isdigit():
                raise ValueError("invalid_player_stat")
            result[key] = int(text)
            if key != "+/-" and result[key] < 0:
                raise ValueError("negative_player_stat")
    for key in ("FG", "3PT", "FT"):
        if key in values:
            parts = str(values[key]).replace("/", "-").split("-")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError("invalid_shooting_stat")
            made, attempts = map(int, parts)
            if made > attempts:
                raise ValueError("invalid_shooting_stat")
            result[key + "M"], result[key + "A"] = made, attempts
    return result


def minutes(value: str) -> tuple[float, str]:
    if ":" in value:
        return clock_ms(value) / 60000, "second"
    if not value.isdigit():
        raise ValueError("invalid_minutes")
    return float(value), "rounded_minute"


def summary(payload: dict, ref: GameRef, observed_at: datetime) -> Evidence:
    header = payload["header"]
    comp = header["competitions"][0]
    if str(header["id"]) != ref.external_id or str(comp["id"]) != ref.external_id:
        raise ValueError("wrong_espn_game")
    tip = stamp(comp["date"])
    teams = competitors(comp)
    normalized = {}
    for side in ("home", "away"):
        row = teams[side]
        abbr = abbreviation(row["team"]["abbreviation"])
        if abbr != getattr(ref, side):
            raise ValueError("wrong_matchup")
        normalized[side] = Team(external_id=str(row["id"]), abbreviation=abbr,
            name=TEAM_NAMES[abbr], score=int(row["score"]),
            periods=tuple(int(s["displayValue"]) for s in row.get("linescores", [])))
    checked_ref = ref.model_copy(update={"scheduled_at": tip})
    if tip.astimezone(EASTERN).date() != ref.day:
        raise ValueError("wrong_nba_day")
    season = header["season"]
    year = int(season["year"])
    if year != ref.day.year + (ref.day.month >= 7):
        raise ValueError("wrong_espn_season")
    game_type = {1: "preseason", 2: "regular_season", 3: "playoffs"}[season["type"]]
    records, record_errors = None, list(ref.record_errors)
    if (game_type == "regular_season" and ref.season_type == 2
            and ref.competition_type is not None and ref.competition_type != "39"
            and ref.final is True and comp["status"]["type"]["completed"] is True):
        try:
            totals = {side: total_record(teams[side], "record") for side in ("home", "away")}
            if (totals["home"] != ref.home_record or totals["away"] != ref.away_record or record_errors):
                raise ValueError("scoreboard_summary_record_mismatch")
            if normalized["home"].score == normalized["away"].score:
                raise ValueError("tied_final_record")
            for side in ("home", "away"):
                won = normalized[side].score > normalized["away" if side == "home" else "home"].score
                if type(teams[side].get("winner")) is not bool or teams[side]["winner"] != won:
                    raise ValueError("record_winner_mismatch")
                total = totals[side]
                if (won and total.wins == 0) or (not won and total.losses == 0):
                    raise ValueError("record_result_cannot_be_removed")
            records = MatchupRecords(home_after=totals["home"], away_after=totals["away"])
        except (ValueError, KeyError, TypeError, AttributeError):
            record_errors.append("invalid_or_inconsistent_completed_game_records")
    else:
        record_errors.append("record_scope_not_verified_regular_season_final")
    pbp_errors, box_errors = [], []
    plays, players = [], []
    try:
        for i, row in enumerate(payload.get("plays", [])):
            if not str(row["id"]).startswith(ref.external_id):
                raise ValueError("wrong_play_identity")
            kind = row["type"]
            plays.append(Play(external_id=str(row["id"]), index=i,
                source_sequence=str(row["sequenceNumber"]) if row.get("sequenceNumber") is not None else None,
                period=row["period"]["number"], remaining_ms=clock_ms(row["clock"]["displayValue"]),
                home=row["homeScore"], away=row["awayScore"], kind=str(kind["id"]),
                period_end=str(kind["id"]) == "412", game_end=str(kind["id"]) == "402",
                participant_ids=tuple(str(v["athlete"]["id"]) for v in row.get("participants", [])),
                wallclock=stamp(row["wallclock"]) if row.get("wallclock") else None,
                scoring=row.get("scoringPlay"), points=row.get("scoreValue")))
    except (ValueError, KeyError, TypeError):
        pbp_errors.append("invalid_play_schema")
        plays = []
    team_errors = {}
    try:
        teams = payload["boxscore"]["players"]
        if not isinstance(teams, list):
            raise ValueError("invalid_box_teams")
    except (KeyError, TypeError, ValueError):
        teams = []
        box_errors.append("invalid_box_schema")
    seen_teams = set()
    for team in teams:
        team_id = str(team.get("team", {}).get("id", "unknown"))
        errors = []
        if team_id in seen_teams:
            errors.append("duplicate_team_box")
        seen_teams.add(team_id)
        try:
            stats = team["statistics"][0]
            for player in stats["athletes"]:
                dnp = player.get("didNotPlay")
                if type(dnp) is not bool:
                    dnp = None
                    errors.append("unknown_participation")
                minute, precision, values = None, "unknown", {}
                if dnp is False:
                    try:
                        values = dict(zip(stats["names"], player["stats"], strict=True))
                        minute, precision = minutes(values["MIN"])
                    except (KeyError, ValueError, TypeError):
                        errors.append("missing_player_minutes")
                try:
                    statistics = parse_statistics(values)
                except (ValueError, KeyError, TypeError):
                    statistics = {}
                    box_errors.append("invalid_player_statistics")
                players.append(PlayerBox(external_id=str(player["athlete"]["id"]), team_id=team_id,
                    name=player["athlete"]["displayName"], starter=player.get("starter"),
                    did_not_play=dnp, minutes=minute, minutes_precision=precision,
                    statistics=statistics))
        except (ValueError, KeyError, TypeError, IndexError):
            errors.append("invalid_team_box_schema")
        if errors:
            team_errors[team_id] = tuple(sorted(set(errors)))
            box_errors.append("partial_team_box")
    meta = payload.get("meta", {})
    def optional_stamp(key):
        try:
            return stamp(meta[key]) if meta.get(key) else None
        except (ValueError, TypeError):
            return None
    return assess(Evidence(provider="espn", external_id=ref.external_id, ref=checked_ref,
        observed_at=observed_at, season=f"{year - 1}-{year}", game_type=game_type,
        status="final" if comp["status"]["type"]["completed"] is True else "pending",
        home=normalized["home"], away=normalized["away"], plays=tuple(plays), players=tuple(players),
        pbp_errors=tuple(pbp_errors), box_errors=tuple(box_errors), box_team_errors=team_errors,
        notes=("source_timestamps_are_not_publication_or_trusted_final",),
        records=records, record_errors=tuple(sorted(set(record_errors))),
        source_end_at=optional_stamp("lastPlayWallClock"), source_updated_at=optional_stamp("lastUpdatedAt")))
