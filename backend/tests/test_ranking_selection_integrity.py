"""Direct ranking consumers must not trust score values without evidence (#10)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from nba_time_machine.ranking import (
    FeatureObservation, PostgameSignal, PregameSignal, ViewingCandidate,
    rank_postgame, rank_pregame, recommend_for_budget, score_postgame,
    score_pregame,
)

A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")
TIP = datetime(2026, 5, 4, 23, tzinfo=timezone.utc)
BEFORE = TIP - timedelta(hours=1)
FINAL = TIP + timedelta(hours=3)
AFTER = FINAL + timedelta(minutes=30)


def pregame(game_id: UUID, value: float):
    return score_pregame(
        game_id,
        {PregameSignal.RIVALRY: FeatureObservation(value, "source:pregame", BEFORE, BEFORE)},
        tip_at=TIP, as_of=BEFORE,
    )


def postgame(game_id: UUID, value: float):
    return score_postgame(
        game_id,
        {PostgameSignal.CLUTCH: FeatureObservation(value, "source:postgame", AFTER, AFTER)},
        final_at=FINAL, as_of=AFTER,
    )


@pytest.mark.parametrize("ranker,score_factory", [
    (rank_pregame, pregame),
    (rank_postgame, postgame),
])
def test_direct_ranker_rejects_corrupt_value_and_provenance(ranker, score_factory):
    good = score_factory(A, .6)
    bad_value = replace(good, value=9.0)
    bad_source = replace(good, components=(
        replace(good.components[0], source_ref=" "),
    ))
    bad_evidence_time = replace(good, components=(
        replace(good.components[0], observed_at=good.as_of + timedelta(seconds=1)),
    ))
    assert ranker((good,)) == (A,)
    for bad in (bad_value, bad_source, bad_evidence_time):
        with pytest.raises(ValueError, match="inconsistent evidence"):
            ranker((bad,))


def test_budget_candidate_checks_evidence_before_selection():
    good = postgame(A, .8)
    assert ViewingCandidate(good, 60).score == good
    for bad in (
        replace(good, value=9.0),
        replace(good, components=(replace(good.components[0], weight=999),)),
        replace(good, components=(replace(good.components[0], normalized_value=.2),)),
    ):
        with pytest.raises(ValueError, match="consistent postgame evidence"):
            ViewingCandidate(bad, 60)


@pytest.mark.parametrize("minutes", [0, 60])
def test_optimizer_rechecks_evidence_even_after_candidate_is_constructed(minutes):
    candidate = ViewingCandidate(postgame(A, .8), 60)
    # Alternate callers can bypass the frozen dataclass with object.__setattr__;
    # the optimizer is itself a final trust boundary, including zero budget.
    object.__setattr__(candidate, "score", replace(candidate.score, value=9.0))
    with pytest.raises(ValueError, match="inconsistent postgame evidence"):
        recommend_for_budget((candidate,), budget_minutes=minutes)


def test_valid_direct_recommendations_remain_deterministic_and_id_only():
    pre_a, pre_b = pregame(A, .2), pregame(B, .9)
    post_a, post_b = postgame(A, .8), postgame(B, .5)
    assert rank_pregame((pre_a, pre_b)) == (B, A)
    assert rank_postgame((post_b, post_a)) == (A, B)
    assert recommend_for_budget(
        (ViewingCandidate(post_b, 60), ViewingCandidate(post_a, 60)),
        budget_minutes=60,
    ) == (A,)
