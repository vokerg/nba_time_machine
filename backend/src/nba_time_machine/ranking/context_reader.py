"""Latest known history revisions, separate from strict pregame ranking facts."""
import json
from datetime import timedelta
from sqlalchemy import select

from nba_time_machine.db import SeasonRecord, SourceRecord, TemporalFactRecord
from nba_time_machine.ranking.game_context import reconstruct
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.sports.standings_history import DayHistory, END, FACT_TYPE, SEASON, SOURCE_ID, START, days


async def read_context(session, evidence, as_of):
    result = {"status": "missing", "reason": "Regular-season history has not been collected.",
        "entering_day": str(evidence.ref.day), "home": None, "away": None,
        "standings": [], "provenance": [], "missing_days": [],
        "basis": "Reconstructed from earlier NBA days; observed later. Not verified pre-tip knowledge.",
        "ranking_note": "Shared ranks by win percentage; official NBA tiebreakers and clinching/elimination math are not applied."}
    if evidence.game_type != "regular_season" or evidence.season != SEASON or not START <= evidence.ref.day <= END:
        return {**result, "status": "not_applicable", "reason": "Context currently supports the reviewed 2025–26 regular season only."}
    try:
        source_policy(await session.get(SourceRecord, SOURCE_ID), "espn", manual=True)
    except ValueError:
        return {**result, "reason": "History source policy is not approved."}
    season = await session.scalar(select(SeasonRecord.id).where(SeasonRecord.league == "NBA", SeasonRecord.label == SEASON))
    if season is None:
        return result
    rows = (await session.scalars(select(TemporalFactRecord).where(
        TemporalFactRecord.season_id == season, TemporalFactRecord.subject_type == "season",
        TemporalFactRecord.source_id == SOURCE_ID, TemporalFactRecord.fact_type == FACT_TYPE,
        TemporalFactRecord.observed_at <= as_of, TemporalFactRecord.available_at <= as_of,
    ).order_by(TemporalFactRecord.observed_at.desc(), TemporalFactRecord.available_at.desc()))).all()
    latest, ambiguous = {}, set()
    for row in rows:
        key = row.fact_metadata.get("day")
        previous = latest.get(key)
        if previous is None:
            latest[key] = row
        elif (row.observed_at, row.available_at) == (previous.observed_at, previous.available_at):
            ambiguous.add(key)
    values = []
    for day in days(START, evidence.ref.day - timedelta(days=1)):
        key = str(day)
        row = latest.get(key)
        try:
            if (row is None or key in ambiguous or row.valid_from > as_of
                    or (row.valid_to is not None and row.valid_to <= as_of)):
                raise ValueError("unavailable_history_day")
            value = DayHistory.model_validate_json(json.dumps(row.value))
            if value.day != day or value.errors:
                raise ValueError("invalid_history_day")
            values.append(value)
            result["provenance"].append({"day": key, "fact_id": str(row.id),
                "source_id": SOURCE_ID, "observed_at": row.observed_at.isoformat(),
                "available_at": row.available_at.isoformat(), "source_url": row.fact_metadata.get("source_url"),
                "results": [r.model_dump(mode="json") for r in value.results]})
        except (ValueError, TypeError):
            result["missing_days"].append(key)
    if result["missing_days"]:
        result["reason"] = "Incomplete or invalid history: every earlier season day is required. Missing data is not zero."
        return result
    try:
        standings = reconstruct(values, evidence.ref.day)
    except ValueError:
        result["reason"] = "History contains conflicting game identities or impossible season totals."
        return result
    result.update(status="available", reason="Complete provider day coverage through the previous NBA day.",
        standings=standings, home=next(r for r in standings if r["team"] == evidence.home.abbreviation),
        away=next(r for r in standings if r["team"] == evidence.away.abbreviation),
        games_used=sum(len(v.results) for v in values))
    return result
