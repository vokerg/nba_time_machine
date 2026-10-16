"""Matchup records from one stored game capture, without rebuilding standings."""
from nba_time_machine.sports.morning_models import TEAM_NAMES
from nba_time_machine.sports.standings_history import CONFERENCES, SEASON, START, END


def game_record_context(evidence, provenance=None):
    result = {"status": "missing", "reason": "This capture has no validated game-supplied records; recollect the game.",
        "entering_day": str(evidence.ref.day), "home": None, "away": None,
        "standings": [], "provenance": [{**(provenance or {}), "game_id": evidence.external_id}],
        "missing_days": [], "source_method": "game_records",
        "basis": "ESPN records attached to this completed game, with this game's result removed. Collected later; not archived pre-tip knowledge.",
        "ranking_note": "These two records do not establish league/conference ranks or playoff stakes; those inputs are unavailable."}
    if (evidence.provider != "espn" or evidence.game_type != "regular_season" or evidence.status != "final"
            or evidence.season != SEASON or not START <= evidence.ref.day <= END
            or evidence.ref.season_type != 2 or evidence.ref.competition_type is None
            or evidence.ref.competition_type == "39"):
        return {**result, "status":"not_applicable", "reason":"Game-supplied context currently requires a reviewed 2025–26 ESPN regular-season final; Cup Championship is excluded."}
    if evidence.records is None or evidence.record_errors or evidence.ref.record_errors:
        result["record_errors"] = list(evidence.record_errors) or ["missing_record_claims"]
        return result
    # Recheck the stored claims: JSON validity is not proof the final result
    # can be subtracted or that these are plausible records for this season day.
    if (evidence.records.home_after != evidence.ref.home_record
            or evidence.records.away_after != evidence.ref.away_record
            or evidence.home.score == evidence.away.score):
        result["reason"] = "Stored summary/scoreboard record claims disagree."
        return result
    rows = []
    for team, after in ((evidence.home, evidence.records.home_after), (evidence.away, evidence.records.away_after)):
        won = team.score > (evidence.away.score if team == evidence.home else evidence.home.score)
        wins, losses = after.wins - int(won), after.losses - int(not won)
        if min(wins, losses) < 0 or after.wins + after.losses > (evidence.ref.day - START).days + 1:
            result["reason"] = "Supplied record cannot represent this game in the reviewed season."
            return result
        gp = wins + losses
        rows.append({"team":team.abbreviation, "name": TEAM_NAMES[team.abbreviation],
            "conference":CONFERENCES[team.abbreviation], "wins":wins, "losses":losses,
            "games_played":gp, "win_pct":wins/gp if gp else None,
            "conference_rank":None, "league_rank":None,
            "provider_after_wins":after.wins, "provider_after_losses":after.losses,
            "removed_result":"win" if won else "loss"})
    return {**result, "status":"available", "reason":"Matching game-specific summary and scoreboard totals; one final result removed per team.",
        "home":rows[0], "away":rows[1]}
