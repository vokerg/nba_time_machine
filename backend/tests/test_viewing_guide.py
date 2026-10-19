"""Two-mode, bounded spoiler-consent regression tests."""
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_game_list import Clock, Acks, Slate, PROFILE, FIRST, SECOND, DAY, CURSOR, TIP, field
from nba_time_machine.api.viewing_guide import get_viewing_guide
from nba_time_machine.main import app
from nba_time_machine.ranking.config import RankingDisclosureSettings
from nba_time_machine.ranking.scoring import FeatureObservation, PostgameSignal, score_postgame
from nba_time_machine.spoilers.policy import GameFieldName as F
from nba_time_machine.spoilers.service import TrustedGameSnapshot
from nba_time_machine.spoilers.viewing_guide import ViewingGuideService, rating_detail

NOW = TIP + timedelta(days=3)
FINAL = TIP + timedelta(hours=3)


class Games:
    def __init__(self):
        self.calls = []

    async def get(self, gid, *, time_cursor):
        self.calls.append(time_cursor)
        return TrustedGameSnapshot(gid, TIP, FINAL, (
            field(F.HOME_TEAM, "Home"), field(F.AWAY_TEAM, "Away"),
            field(F.SCHEDULED_TIP, TIP.isoformat()),
            field(F.HOME_SCORE, 110, FINAL), field(F.AWAY_SCORE, 100, FINAL),
        ), full_available=True)


class Scores:
    def __init__(self):
        self.calls = []
        self.values = (score_postgame(FIRST, {PostgameSignal.CLUTCH: FeatureObservation(
            value=.8, source_ref="fixture:verified", available_at=FINAL, observed_at=FINAL,
        )}, final_at=FINAL, as_of=FINAL),)

    async def postgame_scores_as_of(self, gids, *, as_of):
        self.calls.append(as_of)
        return tuple(s for s in self.values if s.game_id in gids and s.as_of <= as_of)


def setup():
    clock, slates, games, acks, scores = Clock(), Slate(), Games(), Acks(), Scores()
    async def verify(gid, cutoff):
        return next((s for s in scores.values if s.game_id == gid and s.as_of <= cutoff), None)
    service = ViewingGuideService(clock, slates, games, acks, scores, verify,
                                  RankingDisclosureSettings().bands(), now=lambda: NOW)
    return service, clock, slates, games, acks, scores


@pytest.mark.asyncio
async def test_browse_cutoff_is_now_and_date_selection_never_writes_cursor():
    svc, clock, slates, games, acks, scores = setup()
    state, cutoff, result = await svc.list_games(PROFILE, DAY, "browse")
    assert state.time_cursor == CURSOR and cutoff == NOW
    assert all(c == NOW for c in games.calls)
    assert scores.calls == [] and not acks.acknowledged
    assert all(not any(k in g.projection.fields for k in ("home_score", "watchability_verdict")) for g in result.games)
    _, strict, _ = await svc.list_games(PROFILE, DAY, "time-machine")
    assert strict == clock.cursor == CURSOR


@pytest.mark.asyncio
async def test_bulk_reveal_is_date_scoped_and_strict_never_crosses_cutoff_even_when_acknowledged():
    svc, clock, _, _, acks, _ = setup()
    acks.acknowledged.add((PROFILE, FIRST))
    strict = await svc.disclose(PROFILE, DAY, "time-machine", CURSOR, "full")
    assert all("result" not in d and "rating" not in d for d in strict["details"].values())
    browse = await svc.disclose(PROFILE, DAY, "browse", CURSOR, "full")
    assert browse["details"][str(FIRST)]["result"] == {"home_score": 110, "away_score": 100}
    assert browse["details"][str(FIRST)]["rating"] == 8
    assert clock.cursor == CURSOR
    assert (PROFILE, SECOND) in acks.acknowledged
    with pytest.raises(PermissionError):
        await svc.disclose(PROFILE, DAY, "browse", CURSOR, "full", uuid4())


@pytest.mark.asyncio
async def test_order_returns_only_ids_and_unrated_is_not_zero():
    svc, _, _, _, acks, _ = setup()
    result = await svc.disclose(PROFILE, DAY, "browse", CURSOR, "order")
    assert result["details"] == {} and result["game_ids"] == [str(FIRST)]
    assert not acks.acknowledged


@pytest.mark.asyncio
async def test_mismatched_revoked_duplicate_or_corrupt_scores_fail_closed():
    svc, _, _, _, _, scores = setup()
    async def revoked(gid, cutoff):
        return None
    svc.verifier = revoked
    assert not (await svc.disclose(PROFILE, DAY, "browse", CURSOR, "order"))["game_ids"]
    svc, _, _, _, _, scores = setup()
    scores.values *= 2
    assert not (await svc.disclose(PROFILE, DAY, "browse", CURSOR, "order"))["game_ids"]
    scores.values = (replace(scores.values[0], value=9),)
    assert not (await svc.disclose(PROFILE, DAY, "browse", CURSOR, "order"))["game_ids"]


@pytest.mark.asyncio
async def test_cursor_race_rejects_before_acknowledgement():
    svc, clock, _, _, acks, scores = setup()
    with pytest.raises(RuntimeError):
        await svc.disclose(PROFILE, DAY, "browse", NOW, "full")
    assert not scores.calls
    original = scores.postgame_scores_as_of
    async def racing(gids, *, as_of):
        clock.cursor += timedelta(hours=1)
        return await original(gids, as_of=as_of)
    scores.postgame_scores_as_of = racing
    with pytest.raises(RuntimeError):
        await svc.disclose(PROFILE, DAY, "browse", CURSOR, "full")
    assert not acks.acknowledged


def test_rating_layers_and_traceable_component_arithmetic():
    svc, _, _, _, _, scores = setup()
    score = scores.values[0]
    verdict = rating_detail(score, svc.bands, "verdict")
    assert set(verdict) == {"verdict", "has_clue"}
    assert verdict["has_clue"]
    clue = rating_detail(score, svc.bands, "clue")
    assert "close play" in clue["clue"] and "rating" not in clue
    rating = rating_detail(score, svc.bands, "rating")
    assert sum(p["points"] for p in rating["components"]) == rating["rating"]
    assert rating["components"][0]["source_ref"] == "fixture:verified"
    low = replace(score, value=0, components=(replace(score.components[0], normalized_value=0, weighted_contribution=0),))
    assert not rating_detail(low, svc.bands, "verdict")["has_clue"]


def test_http_consent_checked_before_service_and_strict_request_shape():
    class Unavailable:
        async def disclose(self, *args):
            raise AssertionError("must not query data")
    app.dependency_overrides[get_viewing_guide] = lambda: Unavailable()
    body = {"date": DAY.isoformat(), "mode": "browse", "time_cursor": CURSOR.isoformat(), "level": "full"}
    try:
        with TestClient(app) as client:
            path = f"/profiles/{PROFILE}/guide/disclose"
            assert client.post(path, json=body).status_code == 403
            assert client.post(path, json={**body, "consent": True, "unsafe": True}).status_code == 422
            assert client.post(path, json={**body, "consent": True, "level": "rating"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
