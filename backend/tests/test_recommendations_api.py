"""Consent, cursor and spoiler-leakage regression coverage for #10."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from nba_time_machine.api.recommendations import (
    get_watchability_recommendation_service,
)
from nba_time_machine.main import app
from nba_time_machine.ranking import (
    FeatureObservation, PostgameSignal, PregameSignal,
    score_postgame, score_pregame,
)
from nba_time_machine.ranking.service import (
    OutcomeRankingConsentRequired, RecommendationSlateUnavailable,
    RecommendationTimelineChanged, WatchabilityRecommendationService,
)
from nba_time_machine.spoilers.game_list import SafeGameList
from nba_time_machine.spoilers.policy import DisclosureLayer, GameProjection
from nba_time_machine.spoilers.service import DisclosedGame
from nba_time_machine.temporal.timeline import TimelineNotInitializedError, TimelineState

PROFILE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MISSING_PROFILE = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
A = UUID("11111111-1111-4111-8111-111111111111")
B = UUID("22222222-2222-4222-8222-222222222222")
C = UUID("33333333-3333-4333-8333-333333333333")
TIP = datetime(2026, 5, 4, 23, tzinfo=timezone.utc)
FINAL = TIP + timedelta(hours=3)
CURSOR = FINAL + timedelta(minutes=20)
FUTURE = CURSOR + timedelta(hours=1)
SLATE_DATE = date(2026, 5, 4)


def post(game_id: UUID, value: float, *, at: datetime = CURSOR):
    return score_postgame(
        game_id,
        {PostgameSignal.CLUTCH: FeatureObservation(value, "official:final", at, at)},
        final_at=FINAL, as_of=at,
    )


def pre(game_id: UUID, value: float):
    at = TIP - timedelta(hours=1)
    return score_pregame(
        game_id,
        {PregameSignal.RIVALRY: FeatureObservation(value, "official:pregame", at, at)},
        tip_at=TIP, as_of=at,
    )


class Clock:
    def __init__(self):
        self.calls = []

    async def resume(self, profile_id: UUID):
        self.calls.append(profile_id)
        if profile_id != PROFILE:
            raise TimelineNotInitializedError("timeline is not initialized")
        return TimelineState(profile_id, CURSOR, CURSOR, CURSOR)


class Scores:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def postgame_scores_as_of(self, game_ids, *, as_of):
        self.calls.append((game_ids, as_of))
        return self.rows


class Slates:
    def __init__(self, eligible=(A, B, C), *, cursor=CURSOR):
        self.eligible = eligible
        self.cursor = cursor
        self.calls = []

    async def list_games(self, profile_id: UUID, *, slate_date: date):
        self.calls.append((profile_id, slate_date))
        return SafeGameList(
            time_cursor=self.cursor,
            games=tuple(
                DisclosedGame(
                    state="sealed",
                    projection=GameProjection(game_id, DisclosureLayer.PREGAME, {}),
                )
                for game_id in self.eligible
            ),
        )


def setup(rows, *, eligible=(A, B, C), slate_cursor=CURSOR):
    clock, scores = Clock(), Scores(rows)
    slates = Slates(eligible, cursor=slate_cursor)
    return WatchabilityRecommendationService(clock, scores, slates), clock, scores


@pytest.mark.asyncio
async def test_consent_checked_before_profile_or_scores() -> None:
    service, clock, scores = setup((post(A, .9),))
    with pytest.raises(OutcomeRankingConsentRequired):
        await service.recommend(MISSING_PROFILE, (A,), slate_date=SLATE_DATE)
    with pytest.raises(OutcomeRankingConsentRequired):
        await service.recommend(PROFILE, (A,), slate_date=SLATE_DATE, consent_to_outcome_ranking=False)
    assert clock.calls == [] and scores.calls == []


@pytest.mark.asyncio
async def test_rank_only_whitelisted_trusted_and_cursor_available_scores() -> None:
    stale = post(A, .2)
    newer = post(B, .9)
    late = post(C, 1.0, at=FUTURE)
    wrong_kind = pre(C, 1.0)
    wrong_version = replace(post(C, 1.0), model_version="postgame-v999")
    future_component = replace(
        post(C, 1.0),
        components=(replace(post(C, 1.0).components[0], observed_at=FUTURE),),
    )
    service, clock, scores = setup((
        stale, late, newer, wrong_kind, wrong_version, future_component, post(UUID(int=99), 1.0),
    ))
    result = await service.recommend(PROFILE, (A, B, C), slate_date=SLATE_DATE, consent_to_outcome_ranking=True)
    assert result == (B, A)
    assert scores.calls == [((A, B, C), CURSOR)]
    assert clock.calls == [PROFILE]
    assert all(isinstance(game_id, UUID) for game_id in result)


@pytest.mark.asyncio
async def test_recommendations_fail_closed_on_corrupt_archived_score_values() -> None:
    # Even a buggy alternate score repository must not promote a game based on
    # a tampered score or inconsistent feature evidence.
    valid_a, valid_b = post(A, .4), post(B, .8)
    original = post(C, .1)
    inconsistent_value = replace(original, value=10.0)
    inconsistent_signal = replace(
        original,
        components=(replace(original.components[0], signal="team_strength"),),
    )
    inconsistent_weight = replace(
        original,
        components=(replace(original.components[0], weight=999),),
    )
    service, _, _ = setup((
        valid_a, inconsistent_value, valid_b,
        inconsistent_signal, inconsistent_weight,
    ))
    assert await service.recommend(
        PROFILE, (A, B, C), slate_date=SLATE_DATE, consent_to_outcome_ranking=True,
    ) == (B, A)


@pytest.mark.asyncio
async def test_duplicate_archive_rows_fail_closed_without_first_row_bias() -> None:
    # A buggy alternate repository must not rank a game according to the
    # first of multiple snapshots, even when each snapshot is individually valid.
    low_a, high_a, valid_b = post(A, .1), post(A, .99), post(B, .7)
    for rows in (
        (low_a, high_a, valid_b),
        (high_a, valid_b, low_a),
        (low_a, low_a, valid_b),
        (low_a, replace(high_a, model_version="postgame-v999"), valid_b),
    ):
        service, clock, scores = setup(rows)
        assert await service.recommend(
            PROFILE, (A, B), slate_date=SLATE_DATE, consent_to_outcome_ranking=True,
        ) == (B,)
        assert await service.recommend(
            PROFILE, (A, B), slate_date=SLATE_DATE, consent_to_outcome_ranking=True,
            budget_minutes=120, planned_minutes_per_game=120,
        ) == (B,)
        assert clock.calls == [PROFILE, PROFILE]
        assert scores.calls == [((A, B), CURSOR), ((A, B), CURSOR)]


@pytest.mark.asyncio
async def test_budget_uses_user_planned_allocation_not_game_runtime() -> None:
    service, _, _ = setup((post(A, .9), post(B, .8), post(C, .7)))
    ids = (C, A, B)
    assert await service.recommend(
        PROFILE, ids, slate_date=SLATE_DATE, consent_to_outcome_ranking=True,
        budget_minutes=120, planned_minutes_per_game=60,
    ) == (A, B)
    assert await service.recommend(
        PROFILE, ids, slate_date=SLATE_DATE, consent_to_outcome_ranking=True, budget_minutes=0,
    ) == ()
    with pytest.raises(ValueError, match="distinct"):
        await service.recommend(PROFILE, (A, A), slate_date=SLATE_DATE, consent_to_outcome_ranking=True)


@pytest.mark.asyncio
async def test_candidates_must_belong_to_server_projected_slate_before_scores() -> None:
    service, clock, scores = setup((post(A, .9), post(B, .8)), eligible=(A,))
    with pytest.raises(RecommendationSlateUnavailable, match="safe dated slate"):
        await service.recommend(
            PROFILE, (A, B), slate_date=SLATE_DATE, consent_to_outcome_ranking=True,
        )
    assert clock.calls == [PROFILE]
    assert scores.calls == []
    assert service._safe_slates.calls == [(PROFILE, SLATE_DATE)]


@pytest.mark.asyncio
async def test_cursor_mismatch_fails_closed_before_reading_outcomes() -> None:
    service, _, scores = setup(
        (post(A, .9),), slate_cursor=CURSOR + timedelta(minutes=1),
    )
    with pytest.raises(RecommendationTimelineChanged, match="refresh"):
        await service.recommend(
            PROFILE, (A,), slate_date=SLATE_DATE, consent_to_outcome_ranking=True,
        )
    assert scores.calls == []


def test_http_explicit_post_only_and_no_raw_postgame_fields() -> None:
    service, _, scores = setup((post(A, .2), post(B, .9)))
    app.dependency_overrides[get_watchability_recommendation_service] = lambda: service
    try:
        with TestClient(app) as client:
            uri = f"/profiles/{PROFILE}/recommendations/watchability"
            candidate_ids = [str(A), str(B)]
            body = {"candidate_game_ids": candidate_ids, "slate_date": SLATE_DATE.isoformat()}
            assert client.get(uri).status_code == 405
            refusal = client.post(uri, json=body)
            assert refusal.status_code == 403
            assert scores.calls == []
            assert client.post(uri, json={**body, "consent_to_outcome_ranking": False}).status_code == 403
            response = client.post(uri, json={
                **body, "consent_to_outcome_ranking": True,
            })
            assert response.status_code == 200
            assert response.json() == {"game_ids": [str(B), str(A)]}
            wire = response.text
            assert all(token not in wire for token in (
                "score", "value", "components", "official:final", "clutch",
                "model_version", "watchability_verdict", "reason",
            ))
            assert client.post(
                f"/profiles/{MISSING_PROFILE}/recommendations/watchability",
                json={**body, "consent_to_outcome_ranking": True},
            ).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_http_off_slate_ids_and_cursor_races_never_read_hidden_scores() -> None:
    for eligible, slate_cursor, expected in (
        ((A,), CURSOR, 403),
        ((A, B), CURSOR + timedelta(minutes=1), 409),
    ):
        service, _, scores = setup(
            (post(A, .5), post(B, .9)),
            eligible=eligible,
            slate_cursor=slate_cursor,
        )
        app.dependency_overrides[get_watchability_recommendation_service] = lambda: service
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/profiles/{PROFILE}/recommendations/watchability",
                    json={
                        "slate_date": SLATE_DATE.isoformat(),
                        "candidate_game_ids": [str(A), str(B)],
                        "consent_to_outcome_ranking": True,
                    },
                )
                assert response.status_code == expected
                assert scores.calls == []
        finally:
            app.dependency_overrides.clear()


def test_http_rejects_untrusted_payload_fields_duplicates_and_invalid_budget() -> None:
    service, _, scores = setup((post(A, .9),))
    app.dependency_overrides[get_watchability_recommendation_service] = lambda: service
    try:
        with TestClient(app) as client:
            uri = f"/profiles/{PROFILE}/recommendations/watchability"
            base = {
                "candidate_game_ids": [str(A)],
                "slate_date": SLATE_DATE.isoformat(),
                "consent_to_outcome_ranking": True,
            }
            for bad in (
                {**base, "candidate_game_ids": [str(A), str(A)]},
                {**base, "candidate_game_ids": []},
                {**base, "candidate_game_ids": [str(A)] * 33},
                {**base, "score": 10},
                {**base, "time_cursor": FUTURE.isoformat()},
                {**base, "budget_minutes": -1},
                {**base, "budget_minutes": 2000},
                {**base, "planned_minutes_per_game": 0},
                {**base, "consent_to_outcome_ranking": "true"},
                {**base, "slate_date": "not-a-date"},
                {"candidate_game_ids": [str(A)], "consent_to_outcome_ranking": True},
            ):
                assert client.post(uri, json=bad).status_code == 422
            assert scores.calls == []
    finally:
        app.dependency_overrides.clear()
