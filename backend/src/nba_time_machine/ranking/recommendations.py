"""Internal-only recommendation ordering and bounded time-budget optimization.

Return canonical game IDs, not score values, score-sensitive counts, explanatory
metadata or favorite-team boost factors. These functions are NOT a public API:
callers must explicitly authorize any outcome-dependent recommendation surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nba_time_machine.ranking.scoring import (
    ScoreKind, VersionedScore, score_evidence_is_consistent,
)


@dataclass(frozen=True, slots=True)
class ViewingCandidate:
    score: VersionedScore
    duration_minutes: int

    def __post_init__(self) -> None:
        if type(self.score) is not VersionedScore or self.score.kind is not ScoreKind.POSTGAME:
            raise ValueError("time-budget selection requires postgame scores")
        if not score_evidence_is_consistent(self.score):
            raise ValueError("time-budget selection requires consistent postgame evidence")
        if type(self.duration_minutes) is not int or not 0 < self.duration_minutes <= 720:
            raise ValueError("duration must be an integer from 1 to 720 minutes")


def rank_pregame(scores: tuple[VersionedScore, ...]) -> tuple[UUID, ...]:
    return _order(scores, ScoreKind.PREGAME)


def rank_postgame(scores: tuple[VersionedScore, ...]) -> tuple[UUID, ...]:
    return _order(scores, ScoreKind.POSTGAME)


def _order(scores: tuple[VersionedScore, ...], kind: ScoreKind) -> tuple[UUID, ...]:
    if any(type(score) is not VersionedScore or score.kind is not kind for score in scores):
        raise ValueError("cannot mix pregame and postgame ranking evidence")
    if len({score.game_id for score in scores}) != len(scores):
        raise ValueError("one score per game is required")
    if any(not score_evidence_is_consistent(score) for score in scores):
        raise ValueError("cannot rank inconsistent evidence")
    return tuple(score.game_id for score in sorted(scores, key=lambda row: (-row.value, str(row.game_id))))


def recommend_for_budget(
    candidates: tuple[ViewingCandidate, ...], *, budget_minutes: int,
) -> tuple[UUID, ...]:
    """Exact 0/1 knapsack for a bounded slate (up to 32 games, 1440 minutes).

    Maximize hidden summed watchability; deterministic ties prefer less total
    viewing time, then canonical UUID order. Output IDs only. No fandom inputs.
    """
    if type(budget_minutes) is not int or not 0 <= budget_minutes <= 1440:
        raise ValueError("budget must be a whole number of minutes in [0, 1440]")
    if len(candidates) > 32:
        raise ValueError("at most 32 games may be optimized at once")
    if any(type(candidate) is not ViewingCandidate for candidate in candidates):
        raise TypeError("all candidates must be ViewingCandidate")
    if len({candidate.score.game_id for candidate in candidates}) != len(candidates):
        raise ValueError("duplicate game IDs in recommendation slate")
    # Check again at consumption: even a candidate mutated after construction
    # must not influence the hidden-score optimizer.
    if any(not score_evidence_is_consistent(candidate.score) for candidate in candidates):
        raise ValueError("cannot optimize inconsistent postgame evidence")
    if budget_minutes == 0:
        return ()

    ordered = sorted(candidates, key=lambda row: str(row.score.game_id))
    # Each state is (integer utility, sorted game IDs). A dict of attainable
    # durations avoids floating-point comparisons in the optimization itself.
    states: dict[int, tuple[int, tuple[UUID, ...]]] = {0: (0, ())}
    for candidate in ordered:
        points = round(candidate.score.value * 10000)
        minutes = candidate.duration_minutes
        for used, (utility, ids) in list(states.items()):
            new_used = used + minutes
            if new_used > budget_minutes:
                continue
            updated = (utility + points, ids + (candidate.score.game_id,))
            current = states.get(new_used)
            if current is None or updated[0] > current[0] or (updated[0] == current[0] and updated[1] < current[1]):
                states[new_used] = updated
    # Sort using string UUIDs because UUID's comparisons are stable across runtimes.
    _, (_, best_ids) = min(
        states.items(),
        key=lambda item: (-item[1][0], item[0], tuple(str(i) for i in item[1][1])),
    )
    # Canonical UUID ordering is only a deterministic tie-break when choosing
    # the optimal subset. The returned itinerary should prioritize the best
    # hidden watchability within that subset, just like rank_postgame does.
    # Return IDs only: never return the utilities or the hidden score values.
    score_by_id = {candidate.score.game_id: candidate.score.value for candidate in ordered}
    return tuple(sorted(best_ids, key=lambda game_id: (-score_by_id[game_id], str(game_id))))
