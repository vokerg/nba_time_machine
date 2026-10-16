"""Retrospective opening-day records; never authorizes pre-tip visibility."""
from fractions import Fraction
from datetime import timedelta

from nba_time_machine.sports.standings_history import CONFERENCES, START, TEAM_NAMES, days


def reconstruct(history, target_day):
    expected = set(days(START, target_day - timedelta(days=1)))
    if {h.day for h in history} != expected or len(history) != len(expected) or any(h.errors for h in history):
        raise ValueError("incomplete_daily_history")
    rows = {abbr: {"team": abbr, "name": name, "conference": CONFERENCES[abbr],
        "wins": 0, "losses": 0, "result_ids": []} for abbr, name in TEAM_NAMES.items()}
    seen = set()
    for snapshot in history:
        for result in snapshot.results:
            if result.external_id in seen:
                raise ValueError("duplicate_or_later_result")
            seen.add(result.external_id)
            winner = result.home if result.home_score > result.away_score else result.away
            for team in (result.home, result.away):
                rows[team]["wins" if team == winner else "losses"] += 1
                rows[team]["result_ids"].append(result.external_id)
    def pct(row):
        gp = row["wins"] + row["losses"]
        return Fraction(row["wins"], gp) if gp else None
    for row in rows.values():
        row["games_played"] = row["wins"] + row["losses"]
        if row["games_played"] > 82:
            raise ValueError("too_many_regular_season_games")
        value = pct(row)
        row["win_pct"] = float(value) if value is not None else None
        row["league_rank"] = 1 + sum(pct(other) is not None and pct(other) > value
            for other in rows.values()) if value is not None else None
        row["conference_rank"] = 1 + sum(pct(other) is not None and pct(other) > value
            for other in rows.values() if other["conference"] == row["conference"]) if value is not None else None
    # Display order is deterministic; shared ranks preserve ties. Alphabetical
    # ordering within a tie is not an official seeding tiebreaker.
    return sorted(rows.values(), key=lambda row: (row["league_rank"] or 99, row["team"]))
