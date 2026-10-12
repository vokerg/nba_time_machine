"""Regressions for ranking provenance, score-family separation and safe hints."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from nba_time_machine.ranking import (
    FeatureObservation, PostgameSignal, PregameSignal, ScoreKind,
    VerdictBands, ViewingCandidate, rank_postgame, rank_pregame,
    ranking_fields, recommend_for_budget, score_postgame, score_pregame,
)
from nba_time_machine.spoilers.policy import (
    DisclosureLayer, GameContext, project_game,
)

TIP = datetime(2026, 5, 4, 23, tzinfo=timezone.utc)
BEFORE = TIP - timedelta(hours=2)
FINAL = TIP + timedelta(hours=3)
AFTER = FINAL + timedelta(minutes=20)
GAME_A = UUID("00000000-0000-0000-0000-000000000001")
GAME_B = UUID("00000000-0000-0000-0000-000000000002")
GAME_C = UUID("00000000-0000-0000-0000-000000000003")
BANDS = VerdictBands(4, 7, "Low", "Maybe", "Worth watching")


def pre(value: float, *, at: datetime = BEFORE) -> FeatureObservation:
    return FeatureObservation(value, "structured:pregame", at, at)


def post(value: float, *, at: datetime = AFTER) -> FeatureObservation:
    return FeatureObservation(value, "structured:final", at, at)


def pgame(gid: UUID, value: float):
    return score_pregame(gid, {
        PregameSignal.EXPECTED_CLOSENESS: pre(value),
    }, tip_at=TIP, as_of=BEFORE)


def fgame(gid: UUID, value: float):
    return score_postgame(gid, {
        PostgameSignal.CLUTCH: post(value),
    }, final_at=FINAL, as_of=AFTER)


def test_low_profile_game_becomes_exceptional_only_postgame() -> None:
    # A quiet undercard that turns into an unexpected classic must not reorder
    # an earlier pregame slate based on its unknown future outcome.
    low = pgame(GAME_A, 0.2)
    high = pgame(GAME_B, 0.9)
    assert rank_pregame((low, high)) == (GAME_B, GAME_A)
    exceptional = fgame(GAME_A, 1.0)
    routine = fgame(GAME_B, 0.1)
    assert rank_postgame((exceptional, routine)) == (GAME_A, GAME_B)
    assert low.value == 2.0 and exceptional.value == 10.0
    assert "postgame" not in repr(ranking_fields(low))


def test_pregame_rejects_future_backfill_and_tip_boundary() -> None:
    with pytest.raises(ValueError, match="newer than as_of"):
        score_pregame(GAME_A, {
            PregameSignal.RIVALRY: pre(.5, at=TIP - timedelta(minutes=20))
        }, tip_at=TIP, as_of=BEFORE)
    # At the tip itself, evidence is also necessarily later than a pre-tip as_of.
    with pytest.raises(ValueError, match="newer than as_of"):
        score_pregame(GAME_A, {
            PregameSignal.RIVALRY: pre(.5, at=TIP)
        }, tip_at=TIP, as_of=TIP - timedelta(seconds=1))
    with pytest.raises(ValueError, match="precede tipoff"):
        p = score_pregame(GAME_A, {PregameSignal.RIVALRY: pre(.5)}, tip_at=TIP, as_of=TIP)


def test_pregame_rejects_postgame_signal_family_and_untrusted_features() -> None:
    with pytest.raises(ValueError, match="wrong feature family"):
        score_pregame(GAME_A, {PostgameSignal.CLUTCH: pre(1)}, tip_at=TIP, as_of=BEFORE)
    with pytest.raises(TypeError):
        score_pregame(GAME_A, {PregameSignal.RIVALRY: 0.2}, tip_at=TIP, as_of=BEFORE)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_features_require_bounded_finite_values(value) -> None:
    with pytest.raises(ValueError):
        pre(value)


def test_timezone_and_observation_provenance_checked_independently() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        pre(.5, at=datetime(2026, 5, 4, 16))
    with pytest.raises(ValueError, match="newer than as_of"):
        score_pregame(GAME_A, {
            PregameSignal.RIVALRY: FeatureObservation(.5, "official", BEFORE, TIP)
        }, tip_at=TIP, as_of=BEFORE)


def test_postgame_requires_final_and_post_final_evidence() -> None:
    with pytest.raises(ValueError, match="final"):
        score_postgame(GAME_A, {PostgameSignal.CLUTCH: post(.9)}, final_at=FINAL, as_of=BEFORE)
    with pytest.raises(ValueError, match="no earlier than final"):
        score_postgame(GAME_A, {PostgameSignal.CLUTCH: pre(.9)}, final_at=FINAL, as_of=AFTER)


def test_components_are_inspectable_and_order_independent() -> None:
    fields = {
        PregameSignal.STANDINGS_LEVERAGE: pre(.4),
        PregameSignal.EXPECTED_CLOSENESS: pre(.8),
    }
    forward = score_pregame(GAME_A, fields, tip_at=TIP, as_of=BEFORE)
    backward = score_pregame(GAME_A, dict(reversed(list(fields.items()))), tip_at=TIP, as_of=BEFORE)
    assert forward == backward
    assert forward.model_version == "pregame-v1"
    assert {c.signal for c in forward.components} == {"expected_closeness", "standings_leverage"}
    assert all(c.source_ref and c.available_at == BEFORE for c in forward.components)
    assert forward.value == round(10 * (.8 * 25 + .4 * 15) / 40, 4)


def test_disclosure_uses_policy_layer_not_internal_numeric_postgame_score() -> None:
    score = fgame(GAME_A, .99)
    attrs = ranking_fields(score, bands=BANDS, reason="Unexpected late turnaround")
    context = GameContext(GAME_A, BEFORE, TIP, AFTER)
    sealed = project_game(context, DisclosureLayer.PREGAME, attrs)
    coarse = project_game(context, DisclosureLayer.WATCHABILITY, attrs)
    why = project_game(context, DisclosureLayer.WHY, attrs)
    assert sealed.fields == {}
    assert coarse.fields == {"watchability_verdict": "Worth watching"}
    assert why.fields == {**coarse.fields, "watchability_reason": "Unexpected late turnaround"}
    assert "9.9" not in repr(coarse.fields)
    assert "watchability_reason" not in coarse.fields
    with pytest.raises(ValueError, match="require"):
        ranking_fields(score)
    with pytest.raises(ValueError, match="pregame"):
        ranking_fields(pgame(GAME_A, .4), bands=BANDS)


def test_pregame_policy_field_uses_latest_evidence_time() -> None:
    score = pgame(GAME_A, .7)
    context = GameContext(GAME_A, BEFORE, TIP)
    assert project_game(
        context, DisclosureLayer.PREGAME, ranking_fields(score)
    ).fields["pregame_interest"] == 7.0


def test_exact_budget_selection_and_stable_ties_exposes_ids_only() -> None:
    # Non-greedy: two games (60+60) are better than a single 120-minute game.
    a = ViewingCandidate(fgame(GAME_A, 0.8), 120)
    b = ViewingCandidate(fgame(GAME_B, 0.6), 60)
    c = ViewingCandidate(fgame(GAME_C, 0.6), 60)
    assert recommend_for_budget((a, b, c), budget_minutes=120) == (GAME_B, GAME_C)
    assert recommend_for_budget((c, a, b), budget_minutes=120) == (GAME_B, GAME_C)
    assert recommend_for_budget((a, b, c), budget_minutes=0) == ()


def test_budget_rejects_mixed_kind_and_duplicates() -> None:
    with pytest.raises(ValueError, match="postgame"):
        ViewingCandidate(pgame(GAME_A, 1), 60)
    with pytest.raises(ValueError, match="duplicate"):
        recommend_for_budget((
            ViewingCandidate(fgame(GAME_A, .8), 60),
            ViewingCandidate(fgame(GAME_A, .8), 65),
        ), budget_minutes=150)
    with pytest.raises(ValueError, match="budget"):
        recommend_for_budget((), budget_minutes=-1)
    with pytest.raises(ValueError, match="duration"):
        ViewingCandidate(fgame(GAME_A, 1), 0)


def test_canonical_order_has_no_favorites_argument_or_weight() -> None:
    first = fgame(GAME_A, .3)
    second = fgame(GAME_B, .8)
    assert rank_postgame((first, second)) == (GAME_B, GAME_A)
    with pytest.raises(ValueError, match="cannot mix"):
        rank_postgame((first, pgame(GAME_C, .9)))
    with pytest.raises(ValueError, match="one score per game"):
        rank_pregame((pgame(GAME_A, .9), pgame(GAME_A, .2)))


def test_archive_integrity_rejects_score_component_mismatches() -> None:
    from nba_time_machine.ranking.scoring import score_evidence_is_consistent

    good = fgame(GAME_A, .6)
    assert score_evidence_is_consistent(good)
    part = good.components[0]
    corrupt = (
        replace(good, value=9.9),
        replace(good, model_version="postgame-v999"),
        replace(good, components=(replace(part, signal="expected_closeness"),)),
        replace(good, components=(replace(part, normalized_value=.9),)),
        replace(good, components=(replace(part, weight=99),)),
        replace(good, components=(replace(part, weighted_contribution=2.0),)),
        replace(good, components=(replace(part, source_ref=" "),)),
        replace(good, components=(replace(part, observed_at=AFTER + timedelta(seconds=1)),)),
        replace(good, components=(part, part)),
        replace(good, components=(replace(part, normalized_value=float("nan")),)),
    )
    assert all(not score_evidence_is_consistent(score) for score in corrupt)


def test_postgame_archive_reader_filters_corrupt_score_without_older_fallback() -> None:
    from nba_time_machine.ranking.queries import _score_from_row
    from nba_time_machine.ranking.repository import _components

    good = fgame(GAME_B, .7)
    row = SimpleNamespace(
        game_id=good.game_id, score_kind=good.kind.value,
        model_version=good.model_version, as_of=good.as_of,
        score_value=Decimal(str(good.value)), components=_components(good),
    )
    assert _score_from_row(row) == good
    row.score_value = Decimal("9.0")
    assert _score_from_row(row) is None
    row.score_value = Decimal(str(good.value))
    row.components = [{**row.components[0], "weight": 90}]
    assert _score_from_row(row) is None


@pytest.mark.parametrize("kind", ["pregame", "postgame"])
def test_disclosure_bridge_rejects_inconsistent_versioned_evidence(kind: str) -> None:
    # Rendering a score is a distinct consumer boundary: callers may hand it
    # malformed in-memory evidence without going through archive/ranking checks.
    score = pgame(GAME_A, .6) if kind == "pregame" else fgame(GAME_A, .6)
    part = score.components[0]
    kwargs = {} if kind == "pregame" else {
        "bands": BANDS, "reason": "An outstanding finish",
    }
    assert ranking_fields(score, **kwargs)

    corrupt = (
        replace(score, value=9.9),
        replace(score, model_version="forged-v1"),
        replace(score, components=(replace(part, normalized_value=.99),)),
        replace(score, components=(replace(part, weighted_contribution=0),)),
        replace(score, components=(replace(part, source_ref=" "),)),
        replace(score, components=(replace(part, observed_at=score.as_of + timedelta(seconds=1)),)),
        replace(score, components=(part, part)),
    )
    for bad in corrupt:
        with pytest.raises(ValueError, match="inconsistent ranking evidence"):
            ranking_fields(bad, **kwargs)
