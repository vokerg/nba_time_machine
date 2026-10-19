"""Date-scoped fan disclosures. Browse has its own now-bound knowledge clock.

Neither mode mutates the persisted timeline. All outcomes are opt-in POSTs;
strict mode never uses acknowledgement as permission to cross its cutoff.
"""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from nba_time_machine.ranking.scoring import POSTGAME_VERSION, ScoreKind, score_evidence_is_consistent
from nba_time_machine.spoilers.game_list import GameListService
from nba_time_machine.spoilers.guide_cache import PreparedDay
from nba_time_machine.spoilers.policy import DisclosureLayer, GameContext, project_game


class FixedKnowledgeClock:
    def __init__(self, state, cutoff):
        self.state = replace(state, time_cursor=cutoff)

    async def resume(self, profile_id):
        if profile_id != self.state.profile_id:
            raise ValueError("profile mismatch")
        return self.state


LABELS = {
    "clutch": "Close late-game play", "lead_changes": "Lead changes",
    "comeback": "Comeback", "overtime": "Overtime",
    "individual_performance": "Individual performance", "rarity": "Unusual game",
    "game_quality": "Game quality",
}
CLUES = {
    "clutch": "There was close play late in the game.",
    "lead_changes": "The lead changed hands repeatedly.",
    "comeback": "A substantial comeback contributed to this rating.",
    "overtime": "The game went beyond regulation.",
}


def rating_detail(score, bands, level):
    """Serialize only selected fan fields after explicit layer authorization."""
    verdict = bands.high_label if score.value >= bands.high_from else bands.medium_label if score.value >= bands.medium_from else bands.low_label
    result = {"verdict": verdict}
    clues = [CLUES[p.signal] for p in score.components
             if p.signal in CLUES and p.normalized_value >= .5]
    result["has_clue"] = bool(clues)
    if level == "verdict":
        return result
    result["clue"] = clues[0] if clues else None
    if level == "clue":
        return result
    total = sum(p.weight for p in score.components)
    result.update(rating=score.value, model=score.model_version, as_of=score.as_of,
                  components=[{"label": LABELS[p.signal],
                               "points": round(10 * p.weighted_contribution / total, 4),
                               "normalized": p.normalized_value,
                               "source_ref": p.source_ref,
                               "observed_at": p.observed_at,
                               "available_at": p.available_at} for p in score.components])
    return result


class ViewingGuideService:
    def __init__(self, timeline, slates, games, acknowledgements, scores, verifier, bands, now=None, *, cache=None, revision=None):
        self.timeline, self.slates, self.games = timeline, slates, games
        self.acks, self.scores, self.verifier, self.bands = acknowledgements, scores, verifier, bands
        self.cache, self.revision, self.prepared = cache, revision, None
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def context(self, profile_id, day, mode, expected_cursor=None):
        state = await self.timeline.resume(profile_id)
        if expected_cursor is not None and state.time_cursor != expected_cursor:
            raise RuntimeError("timeline changed")
        cutoff = self.now() if mode == "browse" else min(state.time_cursor, self.now())
        if self.cache is None:
            slate = await self._slate(state, cutoff, day)
        else:
            revision = await self.revision(cutoff)
            key = (profile_id, day, mode, state.time_cursor, revision)
            async with self.cache.lock:
                prepared = self.cache.get(key)
                if prepared is None:
                    slate = await self._slate(state, cutoff, day)
                    ids = tuple(g.projection.game_id for g in slate.games)
                    snapshots = await self.games.get_many(ids, time_cursor=cutoff)
                    prepared = PreparedDay(slate, snapshots)
                    self.cache.put(key, prepared)
                self.prepared = prepared
            slate = replace(prepared.slate, time_cursor=cutoff)
        return state, cutoff, slate

    async def _slate(self, state, cutoff, day):
        clock = FixedKnowledgeClock(state, cutoff)
        slate = await GameListService(clock, self.slates, self.games, self.acks,
                                      observed_schedule=True).list_games(state.profile_id, slate_date=day)
        slate = replace(slate, games=tuple(sorted(slate.games, key=lambda game: (
            game.projection.fields.get("scheduled_tip", ""), str(game.projection.game_id)))))
        if len(slate.games) > 32:
            raise RuntimeError("date exceeds disclosure bound")
        return slate

    async def list_games(self, profile_id, day, mode):
        state, cutoff, slate = await self.context(profile_id, day, mode)
        return state, cutoff, slate

    async def disclose(self, profile_id, day, mode, expected_cursor, level, game_id=None):
        state, cutoff, slate = await self.context(profile_id, day, mode, expected_cursor)
        ids = tuple(g.projection.game_id for g in slate.games)
        if game_id is not None and game_id not in ids:
            raise PermissionError("game is not on this date")
        selected = (game_id,) if game_id else ids
        if self.prepared is None:
            eligible = await self._eligible_scores(selected, cutoff)
        else:
            # Consent authorizes only the requested response fields. Prepare the
            # internal day's ratings once so other games/layers reuse the work.
            async with self.cache.lock:
                if self.prepared.scores is None:
                    self.prepared.scores = await self._eligible_scores(ids, cutoff)
            eligible = {gid: self.prepared.scores[gid] for gid in selected
                        if gid in self.prepared.scores}
        details = {}
        pending_acks = []
        for gid in selected:
            item = {"game_id": str(gid)}
            if gid in eligible and level != "order":
                item.update(rating_detail(eligible[gid], self.bands, level))
            if level == "full":
                snapshot = (self.prepared.snapshots.get(gid) if self.prepared is not None
                            else await self.games.get(gid, time_cursor=cutoff))
                if (snapshot is not None and snapshot.full_available
                        and snapshot.tip_at is not None and snapshot.tip_at < cutoff
                        and snapshot.protection_ends_at is not None
                        and snapshot.tip_at < snapshot.protection_ends_at <= cutoff):
                    # Filter BEFORE projection: explicit reveal/old acknowledgements
                    # cannot grant Time Machine a post-cursor exception.
                    known = tuple(f for f in snapshot.fields
                                  if f.available_at is not None and f.observed_at is not None
                                  and f.available_at <= cutoff and f.observed_at <= cutoff)
                    context = GameContext(gid, cutoff, snapshot.tip_at, snapshot.protection_ends_at,
                                          acknowledged=True, observed_schedule=True)
                    projected = project_game(context, DisclosureLayer.FULL, known)
                    if all(k in projected.fields for k in ("home_score", "away_score")):
                        item["result"] = {k: projected.fields[k] for k in ("home_score", "away_score")}
                        pending_acks.append(gid)
            details[str(gid)] = item
        if (await self.timeline.resume(profile_id)).time_cursor != state.time_cursor:
            raise RuntimeError("timeline changed")
        for gid in pending_acks:
            await self.acks.acknowledge(profile_id, gid)
        order = sorted(eligible, key=lambda gid: (-eligible[gid].value, str(gid)))
        return {"time_cursor": state.time_cursor, "as_of": cutoff,
                "details": details if level != "order" else {}, "game_ids": [str(gid) for gid in order] if game_id is None else []}

    async def _eligible_scores(self, game_ids, cutoff):
        archived = await self.scores.postgame_scores_as_of(game_ids, as_of=cutoff)
        eligible = {}
        for gid in game_ids:
            matches = [s for s in archived if s.game_id == gid]
            if len(matches) != 1 or not score_evidence_is_consistent(matches[0]):
                continue
            score = matches[0]
            if score.kind is not ScoreKind.POSTGAME or score.model_version != POSTGAME_VERSION or score.as_of > cutoff:
                continue
            # Re-derive only for integrity, never to introduce a new score/model.
            # Current revoked, revised or incomplete evidence withholds the archive.
            trusted = await self.verifier(gid, cutoff)
            if trusted is not None and (trusted.model_version, trusted.value, trusted.components) == (score.model_version, score.value, score.components):
                eligible[gid] = score
        return eligible
