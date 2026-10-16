"""Bounded, read-only operational projections. Never return captured payloads."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import aliased

from nba_time_machine.db import (
    CollectionRunRecord, GameObservationRecord, GameRecord, SeasonRecord,
    SourceOutcomeRecord, SourceRecord, TeamRecord, TemporalFactRecord,
)

EASTERN = ZoneInfo("America/New_York")
BAD = {"blocked", "auth_error", "rate_limited", "parse_error", "network_error", "skipped_config", "partial"}
SAFE_CODE = re.compile(r"[a-z][a-z0-9_:-]{0,63}\Z")


def code(value):
    """Error codes only. No exception text, response excerpts, URLs or identifiers."""
    return value if isinstance(value, str) and SAFE_CODE.fullmatch(value) else ("redacted" if value else None)


def stamp(value):
    return value.isoformat() if value is not None else None


def freshness(source, outcome, now):
    """An enabled flag never establishes successful or current collection."""
    if not source.enabled:
        return "disabled"
    if source.verification_status != "verified":
        return "unverified"
    if outcome is None or outcome.finished_at is None:
        return "unknown"
    if outcome.status in BAD:
        return "failing"
    if outcome.finished_at > now:
        return "unknown"
    if now - outcome.finished_at > timedelta(minutes=2 * source.cadence_minutes):
        return "stale"
    return "idle_recent" if outcome.status == "idle" else "recent_check"


def family(value, flag, rows, errors):
    """Avoid interpreting absence of evidence as a zero or a successful collection."""
    if value.get("status") != "final":
        return "not_final"
    if value.get(flag) is True or (bool(value.get(rows)) and not value.get(errors)):
        return "complete"
    return "partial" if rows in value or errors in value else "not_collected"


def summarize_evidence(facts):
    """Per-family selection; source IDs describe provenance without merging provider rows."""
    pbp, box = [], []
    latest = None
    for fact in facts:
        value = fact.value if isinstance(fact.value, dict) else {}
        if latest is None or fact.observed_at > latest:
            latest = fact.observed_at
        pbp.append((family(value, "pbp_usable", "plays", "pbp_errors"), fact.source_id))
        box.append((family(value, "box_usable", "players", "box_errors"), fact.source_id))

    def choose(entries):
        for status in ("complete", "partial", "not_final"):
            match = next((provider for result, provider in entries if result == status), None)
            if match:
                return {"status": status, "source": match}
        return {"status": "not_collected", "source": None}

    return {"play_by_play": choose(pbp), "player_box": choose(box),
            "team_box": {"status": "unsupported", "source": None},
            "latest_evidence_observed_at": stamp(latest)}


async def build_report(session, *, day=None, season=None, source=None, status=None, now=None):
    """One Eastern day, bounded evidence; no collector invocation or writes."""
    now = now or datetime.now(timezone.utc)
    day = day or now.astimezone(EASTERN).date()
    if season and (len(season) > 64 or not re.fullmatch(r"[0-9]{4}-[0-9]{4}", season)):
        raise ValueError("invalid_season")
    if source and (len(source) > 160 or not re.fullmatch(r"[a-zA-Z0-9_.-]+", source)):
        raise ValueError("invalid_source")
    if status and status not in {"ok", "idle", "partial", "skipped_config", "blocked", "auth_error", "rate_limited", "parse_error", "network_error"}:
        raise ValueError("invalid_status")

    sources = list((await session.scalars(select(SourceRecord).order_by(SourceRecord.id).limit(501))).all())
    runs = list((await session.scalars(select(CollectionRunRecord).order_by(
        CollectionRunRecord.started_at.desc()).limit(61))).all())
    outcomes = list((await session.scalars(select(SourceOutcomeRecord).order_by(
        SourceOutcomeRecord.finished_at.desc().nullslast()).limit(2001))).all())
    if len(sources) > 500 or len(runs) > 60 or len(outcomes) > 2000:
        raise ValueError("operational_query_limit_exceeded")

    last, good, last_attempt = {}, {}, {}
    for outcome in outcomes:
        last.setdefault(outcome.source_id, outcome)
        if outcome.status == "ok":
            good.setdefault(outcome.source_id, outcome.finished_at)
        if outcome.finished_at:
            last_attempt.setdefault(outcome.source_id, outcome.finished_at)
    source_rows = [{
        "id": s.id, "name": s.name[:160], "configured": True,
        "verified": s.verification_status, "enabled": s.enabled,
        "requires_auth": s.requires_auth, "cadence_minutes": s.cadence_minutes,
        "last_attempt_at": stamp(last_attempt.get(s.id)),
        "last_success_at": stamp(good.get(s.id)),
        "last_outcome": last[s.id].status if s.id in last else None,
        "freshness": freshness(s, last.get(s.id), now),
        "last_error_code": code(last[s.id].error_code) if s.id in last else None,
    } for s in sources if source is None or s.id == source]
    filtered_outcomes = [o for o in outcomes if (not source or o.source_id == source)
                         and (not status or o.status == status)]
    recent_outcomes = [{
        "run_id": str(o.collection_run_id), "source_id": o.source_id,
        "status": o.status, "items_seen": o.items_seen,
        "captures_written": o.captures_written,
        "finished_at": stamp(o.finished_at), "error_code": code(o.error_code),
    } for o in filtered_outcomes[:80]]
    matched_ids = {o.collection_run_id for o in filtered_outcomes}
    recent_runs = [{
        "id": str(r.id), "started_at": stamp(r.started_at),
        "finished_at": stamp(r.finished_at), "collector": r.collector_version,
    } for r in runs if not status or r.id in matched_ids][:50]

    # Find the NBA day by the observation's recorded scheduled tip. A missing
    # scheduled tip cannot be assigned a date without inventing one.
    start = datetime.combine(day, time.min, EASTERN).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, EASTERN).astimezone(timezone.utc)
    home, away = aliased(TeamRecord), aliased(TeamRecord)
    query = (select(GameObservationRecord, SeasonRecord.label, home.name, away.name)
        .join(GameRecord, GameRecord.id == GameObservationRecord.game_id)
        .join(SeasonRecord, SeasonRecord.id == GameRecord.season_id)
        .join(home, home.id == GameRecord.home_team_id)
        .join(away, away.id == GameRecord.away_team_id)
        .where(SeasonRecord.league == "NBA",
            GameObservationRecord.scheduled_tip_at >= start,
            GameObservationRecord.scheduled_tip_at < end)
        .order_by(GameObservationRecord.observed_at.desc()).limit(1001))
    if season:
        query = query.where(SeasonRecord.label == season)
    observations = (await session.execute(query)).all()
    if len(observations) > 1000:
        raise ValueError("operational_query_limit_exceeded")
    latest_games = {}
    for observation, season_label, home_name, away_name in observations:
        latest_games.setdefault(observation.game_id,
            (observation, season_label, home_name, away_name))

    ids = list(latest_games)
    facts = list((await session.scalars(select(TemporalFactRecord).where(
        TemporalFactRecord.game_id.in_(ids),
        TemporalFactRecord.fact_type == "provider_game_evidence",
    ).order_by(TemporalFactRecord.observed_at.desc()).limit(2501))).all()) if ids else []
    if len(facts) > 2500:
        raise ValueError("operational_query_limit_exceeded")
    by_game = {}
    for fact in facts:
        key = (fact.game_id, fact.source_id)
        if not any(f.source_id == fact.source_id for f in by_game.get(fact.game_id, [])):
            by_game.setdefault(fact.game_id, []).append(fact)

    games = []
    for observation, season_label, home_name, away_name in latest_games.values():
        evidence = summarize_evidence(by_game.get(observation.game_id, []))
        games.append({
            "game_id": str(observation.game_id), "season": season_label, "day": day.isoformat(),
            "home": home_name[:120], "away": away_name[:120],
            "status": observation.status, "observation_source": observation.source_id,
            "scheduled_tip_at": stamp(observation.scheduled_tip_at),
            "last_observed_at": stamp(observation.observed_at), **evidence,
        })
    games.sort(key=lambda g: (g["scheduled_tip_at"] or "", g["game_id"]))
    return {"day": day.isoformat(), "season": season, "source_filter": source,
            "status_filter": status, "generated_at": stamp(now),
            "sources": source_rows, "outcomes": recent_outcomes,
            "runs": recent_runs, "games": games,
            "limits": {"sources": 500, "runs": 60, "outcomes": 2000, "observations": 1000, "evidence_facts": 2500},
            "notes": ["Read-only operator view. Source configuration is not proof of collection.",
                      "A recorded final status is a provider claim, not a trusted final timestamp.",
                      "Team box is unsupported in this normalized family; absence of games is not a verified empty slate.",
                      "Observation/capture times reflect collection, not event or publisher publication times."]}
