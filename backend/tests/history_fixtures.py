"""Synthetic source-shaped daily scoreboards; no live source payloads."""
from datetime import datetime, time, timezone


def scoreboard(day, *, completed=True, kind=2, competition_type="1"):
    tip = datetime.combine(day, time(23), timezone.utc).isoformat()
    return {"leagues": [{"abbreviation": "NBA", "season": {"year": 2026}}], "events": [{
        "id": "10001", "date": tip, "season": {"year": 2026, "type": kind},
        "status": {"type": {"completed": completed, "name": "STATUS_FINAL"}},
        "competitions": [{"type": {"id": competition_type}, "competitors": [
            {"homeAway": "home", "team": {"abbreviation": "BOS"}, "score": "110"},
            {"homeAway": "away", "team": {"abbreviation": "NY"}, "score": "100"}]}]}]}
