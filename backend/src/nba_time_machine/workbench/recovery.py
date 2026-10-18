"""Conservative cross-provider interpretation for local previews only.

Never mutates captures, changes production eligibility, or treats CBS as a complete
trajectory. A missing action alone is insufficient: matching player totals and a
same-clock jump ball must uniquely corroborate one surplus free throw.
"""
from collections import Counter
import re

from pydantic import ValidationError
from sqlalchemy import select

from nba_time_machine.db import (GameObservationRecord, SourceRecord,
    SportsExternalIdentityRecord, TemporalFactRecord)
from nba_time_machine.sports.morning import SOURCE_IDS
from nba_time_machine.sports.morning_models import Evidence, assess, scoring_action_states
from nba_time_machine.sports.morning_store import source_policy

VERSION = "cbs_corroborated_free_throw_v1"


def signature(play):
    # CBS truncates fractional seconds. Keep provider order; never sort events.
    return (play.period, play.remaining_ms // 1000, play.points,
            play.free_throw_attempt)


def recover_free_throw(primary: Evidence, backup: Evidence):
    primary, backup = assess(primary), assess(backup)
    if (primary.provider != "espn" or backup.provider != "cbs"
            or primary.status != "final" or backup.status != "final"
            or primary.trajectory_basis != "provider_scores"
            or not primary.box_usable
            or not primary.pbp_errors
            or not set(primary.pbp_errors) <= {"period_end_mismatch", "terminal_mismatch"}
            or primary.ref.key != backup.ref.key
            or primary.ref.scheduled_at is None
            or primary.ref.scheduled_at != backup.ref.scheduled_at
            or primary.season != backup.season or primary.game_type != backup.game_type
            or any((getattr(primary, side).score, getattr(primary, side).periods) !=
                   (getattr(backup, side).score, getattr(backup, side).periods)
                   for side in ("home", "away"))):
        return None
    states = scoring_action_states(primary)
    if (not states or any(p.index != i for e in (primary, backup)
                          for i, p in enumerate(e.plays))):
        return None
    # A single player's total must be exactly one point over their complete box;
    # every other player's scoring actions must already reconcile.
    scoring = [p for p in primary.plays if p.scoring]
    names = [p.name for p in primary.players]
    if len(set(names)) != len(names) or any(p.scorer_name not in names for p in scoring):
        return None
    totals = Counter()
    for p in scoring:
        totals[p.scorer_name] += p.points
    excess = [(p, totals[p.name] - p.statistics.get("PTS", 0)) for p in primary.players
              if p.did_not_play is False and totals[p.name] != p.statistics.get("PTS", 0)]
    if len(excess) != 1 or excess[0][1] != 1:
        return None
    player = excess[0][0]
    team = next((t for t in (primary.home, primary.away) if t.external_id == player.team_id), None)
    backup_team = getattr(backup, "home" if team == primary.home else "away")
    slug = re.sub(r"[^a-z0-9]+", "-", player.name.lower()).strip("-")
    if sum(re.sub(r"[^a-z0-9]+", "-", p.name.lower()).strip("-") == slug
           for p in primary.players) != 1:
        return None
    boxes = [p for p in backup.players if p.name == player.name or p.profile_slug == slug]
    if (team is None or len(boxes) != 1 or boxes[0].team_id != backup_team.external_id
            or boxes[0].did_not_play is not False
            or any(boxes[0].statistics.get(k) != player.statistics.get(k)
                   for k in ("PTS", "FGM", "3PTM", "FTM", "FTA"))):
        return None
    own = [p for p in scoring if p.scorer_name == player.name]
    other = [p for p in backup.plays if p.scoring and p.scorer_name == player.name]
    candidates = []
    for play in own:
        if play.points != 1 or play.free_throw_attempt != 2 or play.scoring_team_id != player.team_id:
            continue
        previous = primary.plays[play.index - 1] if play.index else None
        if (previous is None or previous.scorer_name != player.name or previous.free_throw_attempt != 1
                or not previous.scoring or previous.points != 1
                or (previous.period, previous.remaining_ms) != (play.period, play.remaining_ms)):
            continue
        first = [p for p in other if signature(p) == signature(previous)]
        if len(first) != 1 or not any(j.index > first[0].index and j.period == play.period
                   and j.remaining_ms == play.remaining_ms
                   and player.name in j.jump_ball_players for j in backup.plays):
            continue
        remaining = [p for p in own if p.index != play.index]
        if ([signature(p) for p in remaining] != [signature(p) for p in other]
                or sum(p.points for p in remaining if p.free_throw_attempt) != player.statistics.get("FTM")
                or sum(p.points for p in remaining if not p.free_throw_attempt) !=
                   2 * player.statistics.get("FGM", 0) + player.statistics.get("3PTM", 0)):
            continue
        # No fabricated event or clock: retain the provider action in the original
        # evidence and interpret only its scoring contribution as nullified.
        actions = tuple(p.model_copy(update={"scoring": False, "points": 0})
                        if p.index == play.index else p for p in primary.plays)
        raw = primary.model_copy(update={"plays": actions})
        rebuilt = scoring_action_states(raw)
        if rebuilt is None:
            continue
        plays = tuple(p.model_copy(update={"home": h, "away": a,
            "reported_home": p.home, "reported_away": p.away})
            for p, (h, a) in zip(actions, rebuilt, strict=True))
        candidate = assess(raw.model_copy(update={"plays": plays, "pbp_errors": (),
            "trajectory_basis": "scoring_actions_v1", "reported_pbp_errors": primary.pbp_errors}))
        if candidate.pbp_usable:
            candidates.append((candidate, {"version": VERSION, "player": player.name,
                "original_action": play.model_dump(mode="json"),
                "interpretation": "Surplus made free throw treated as nullified; corroborated by CBS jump ball, player box and every period/final total."}))
    return candidates[0] if len(candidates) == 1 else None


async def preview_recovery(session, observation, as_of):
    """Require both latest, unambiguous, current, mapped and approved inputs."""
    inputs = {}
    for provider, source_id in SOURCE_IDS.items():
        f, o = TemporalFactRecord, GameObservationRecord
        facts = (await session.scalars(select(f).where(f.game_id == observation.game_id,
            f.fact_type == "provider_game_evidence", f.source_id == source_id,
            f.observed_at <= as_of, f.available_at <= as_of)
            .order_by(f.observed_at.desc(), f.available_at.desc()).limit(2))).all()
        observations = (await session.scalars(select(o).where(o.game_id == observation.game_id,
            o.source_id == source_id, o.observed_at <= as_of, o.available_at <= as_of)
            .order_by(o.observed_at.desc(), o.available_at.desc()).limit(2))).all()
        if any(not rows or (len(rows) == 2 and
               (rows[0].observed_at, rows[0].available_at) ==
               (rows[1].observed_at, rows[1].available_at)) for rows in (facts, observations)):
            return None
        fact, obs = facts[0], observations[0]
        if (fact.valid_from > as_of or (fact.valid_to is not None and fact.valid_to <= as_of)
                or (fact.observed_at, fact.available_at) != (obs.observed_at, obs.available_at)
                or obs.status != "final" or observation.status != "final"
                or (obs.home_score, obs.away_score, obs.scheduled_tip_at) !=
                   (observation.home_score, observation.away_score, observation.scheduled_tip_at)):
            return None
        try:
            source_policy(await session.get(SourceRecord, source_id), provider, manual=True)
            evidence = Evidence.model_validate({**fact.value, "observed_at": fact.observed_at})
        except (ValueError, ValidationError, TypeError):
            return None
        mapped = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
            SportsExternalIdentityRecord.provider_key == provider,
            SportsExternalIdentityRecord.entity_type == "game",
            SportsExternalIdentityRecord.external_id == evidence.external_id))
        if (mapped != observation.game_id or evidence.provider != provider
                or (provider == "espn" and evidence.ref.external_id != evidence.external_id)
                or (provider == "cbs" and evidence.ref.external_id != evidence.ref.cbs_abbr)
                or evidence.ref.scheduled_at != obs.scheduled_tip_at
                or obs.scheduled_tip_at is None
                or min(fact.observed_at, fact.available_at) <= obs.scheduled_tip_at
                or (evidence.home.score, evidence.away.score) != (obs.home_score, obs.away_score)):
            return None
        inputs[provider] = (fact, evidence)
    recovered = recover_free_throw(inputs["espn"][1], inputs["cbs"][1])
    if recovered is None:
        return None
    effective, proof = recovered
    proof["inputs"] = [{"provider": provider, "fact_id": str(fact.id),
        "observed_at": fact.observed_at.isoformat(), "available_at": fact.available_at.isoformat()}
        for provider, (fact, _) in inputs.items()]
    proof["effective_evidence"] = effective.model_dump(mode="json")
    return inputs["espn"][0], inputs["espn"][1], effective, proof
