from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from nba_time_machine.api.game_disclosure import get_game_disclosure_service
from nba_time_machine.main import app
from nba_time_machine.spoilers.policy import (
    DisclosureLayer, GameField, GameFieldName, MediaField, MediaFieldName,
    MediaItem, MediaSensitivity,
)
from nba_time_machine.spoilers.service import (
    GameDisclosureService, GameNotFoundError, GameResultNotAvailableError,
    SealedGameError, TrustedGameSnapshot,
)
from nba_time_machine.temporal import TimelineState

CURSOR = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
TIP = CURSOR + timedelta(hours=12)
FINAL = TIP + timedelta(hours=3)
GAME_ID = UUID("11111111-1111-4111-8111-111111111111")


@dataclass
class FakeTimeline:
    cursor: datetime = CURSOR

    async def resume(self, profile_id: UUID) -> TimelineState:
        return TimelineState(profile_id, self.cursor, self.cursor, self.cursor)


class FakeAcks:
    def __init__(self) -> None:
        self.rows: set[tuple[UUID, UUID]] = set()
        self.writes = 0

    async def is_acknowledged(self, profile_id: UUID, game_id: UUID) -> bool:
        return (profile_id, game_id) in self.rows

    async def acknowledge(self, profile_id: UUID, game_id: UUID) -> None:
        self.writes += 1
        self.rows.add((profile_id, game_id))


class FakeGames:
    def __init__(self, snapshot: TrustedGameSnapshot) -> None:
        self.snapshot = snapshot

    async def get(self, game_id: UUID, *, time_cursor: datetime) -> TrustedGameSnapshot | None:
        return self.snapshot if game_id == self.snapshot.game_id else None


def fact(name: GameFieldName, value: str | int, at: datetime) -> GameField:
    return GameField(name, value, at, at)


def snapshot(*, complete: bool = True, boundary: datetime | None = FINAL) -> TrustedGameSnapshot:
    fields = (
        fact(GameFieldName.HOME_TEAM, "Home", CURSOR),
        fact(GameFieldName.AWAY_TEAM, "Away", CURSOR),
        fact(GameFieldName.SCHEDULED_TIP, TIP.isoformat(), CURSOR),
        fact(GameFieldName.WATCHABILITY_VERDICT, "Worth it", FINAL),
        fact(GameFieldName.WATCHABILITY_REASON, "Late run", FINAL),
        fact(GameFieldName.HOME_SCORE, 110, FINAL),
        fact(GameFieldName.AWAY_SCORE, 108, FINAL),
    )
    return TrustedGameSnapshot(
        GAME_ID, TIP, boundary, fields, full_available=complete,
    )


def setup(*, complete: bool = True, boundary: datetime | None = FINAL):
    clock = FakeTimeline()
    acks = FakeAcks()
    service = GameDisclosureService(clock, FakeGames(snapshot(complete=complete, boundary=boundary)), acks)
    return service, clock, acks


@pytest.mark.asyncio
async def test_layers_are_independent_and_full_get_does_not_implicitly_acknowledge() -> None:
    service, clock, acks = setup()
    profile = uuid4()
    pre = await service.disclose(profile, GAME_ID, DisclosureLayer.PREGAME)
    verdict = await service.disclose(profile, GAME_ID, DisclosureLayer.WATCHABILITY)
    reason = await service.disclose(profile, GAME_ID, DisclosureLayer.WHY)

    assert pre.state == verdict.state == reason.state == "sealed"
    assert pre.projection.fields["home_team"] == "Home"
    assert "home_score" not in pre.projection.fields
    assert verdict.projection.fields["watchability_verdict"] == "Worth it"
    assert "watchability_reason" not in verdict.projection.fields
    assert reason.projection.fields["watchability_reason"] == "Late run"
    assert "home_score" not in reason.projection.fields

    with pytest.raises(SealedGameError):
        await service.disclose(profile, GAME_ID, DisclosureLayer.FULL)
    assert acks.rows == set()
    assert clock.cursor == CURSOR


@pytest.mark.asyncio
async def test_explicit_full_reveal_is_durable_idempotent_and_profile_scoped() -> None:
    service, clock, acks = setup()
    profile, other = uuid4(), uuid4()

    first = await service.reveal_full(profile, GAME_ID)
    again = await service.reveal_full(profile, GAME_ID)
    assert first.state == again.state == "acknowledged"
    assert first.projection.fields["home_score"] == 110
    assert again.projection == first.projection
    assert len(acks.rows) == 1
    assert acks.writes == 1
    assert (profile, GAME_ID) in acks.rows
    assert clock.cursor == CURSOR
    assert (await service.disclose(other, GAME_ID, DisclosureLayer.PREGAME)).state == "sealed"
    with pytest.raises(SealedGameError):
        await service.disclose(other, GAME_ID, DisclosureLayer.FULL)


@pytest.mark.asyncio
async def test_future_unresolved_game_is_not_preacknowledged() -> None:
    service, _, acks = setup(complete=False)
    with pytest.raises(GameResultNotAvailableError):
        await service.reveal_full(uuid4(), GAME_ID)
    assert not acks.rows
    # A derived unsealed state is not proof that a usable score exists.
    service._timeline.cursor = FINAL
    with pytest.raises(GameResultNotAvailableError):
        await service.reveal_full(uuid4(), GAME_ID)
    assert not acks.rows


@pytest.mark.asyncio
async def test_timeline_boundary_unseals_without_writing_fake_acknowledgement() -> None:
    service, clock, acks = setup()
    profile = uuid4()
    clock.cursor = FINAL - timedelta(microseconds=1)
    assert (await service.disclose(profile, GAME_ID, DisclosureLayer.PREGAME)).state == "sealed"
    clock.cursor = FINAL
    assert (await service.disclose(profile, GAME_ID, DisclosureLayer.PREGAME)).state == "acknowledged"
    assert (await service.disclose(profile, GAME_ID, DisclosureLayer.FULL)).projection.fields["home_score"] == 110
    await service.reveal_full(profile, GAME_ID)
    assert acks.rows == {(profile, GAME_ID)}  # Only the explicit POST writes a record.

    protected, late_clock, late_acks = setup(boundary=None)
    late_clock.cursor = FINAL + timedelta(days=4)
    assert (await protected.disclose(profile, GAME_ID, DisclosureLayer.PREGAME)).state == "sealed"
    assert not late_acks.rows


@pytest.mark.asyncio
async def test_acknowledgement_cannot_expose_postcursor_global_media() -> None:
    service, _, _ = setup()
    profile = uuid4()
    news = (
        MediaItem(
            "before", CURSOR, CURSOR, MediaSensitivity.PREGAME,
            frozenset({GAME_ID}),
            (MediaField(MediaFieldName.HEADLINE, "Preview", CURSOR, CURSOR),),
        ),
        MediaItem(
            "after", FINAL, FINAL, MediaSensitivity.OUTCOME_DEPENDENT,
            frozenset({GAME_ID}),
            (MediaField(MediaFieldName.HEADLINE, "Final score", FINAL, FINAL),),
        ),
    )
    assert [x.item_id for x in await service.general_media(profile, news)] == ["before"]
    await service.reveal_full(profile, GAME_ID)
    assert [x.item_id for x in await service.general_media(profile, news)] == ["before"]


@pytest.mark.asyncio
async def test_unknown_games_fail_closed() -> None:
    service, _, _ = setup()
    with pytest.raises(GameNotFoundError):
        await service.disclose(uuid4(), uuid4(), DisclosureLayer.PREGAME)



@pytest.mark.asyncio
async def test_timeline_unsealing_does_not_leak_future_score_corrections() -> None:
    clock = FakeTimeline(cursor=FINAL)
    acks = FakeAcks()
    future_correction = fact(
        GameFieldName.HOME_SCORE, 120, FINAL + timedelta(days=1),
    )
    original = snapshot()
    corrected = TrustedGameSnapshot(
        GAME_ID, TIP, FINAL,
        tuple(f for f in original.fields if f.name is not GameFieldName.HOME_SCORE)
        + (future_correction,),
        full_available=True,
    )
    service = GameDisclosureService(clock, FakeGames(corrected), acks)
    profile = uuid4()
    passive = await service.disclose(profile, GAME_ID, DisclosureLayer.FULL)
    assert "home_score" not in passive.projection.fields
    assert acks.rows == set()
    explicit = await service.reveal_full(profile, GAME_ID)
    assert explicit.projection.fields["home_score"] == 120
    assert acks.rows == {(profile, GAME_ID)}
    assert (await service.disclose(profile, GAME_ID, DisclosureLayer.FULL)).projection.fields["home_score"] == 120

def test_api_requires_explicit_post_for_full_result_and_exposes_sparse_models() -> None:
    service, _, _ = setup()
    profile = uuid4()
    uri = f"/profiles/{profile}/games/{GAME_ID}"
    app.dependency_overrides[get_game_disclosure_service] = lambda: service
    try:
        with TestClient(app) as client:
            assert client.get(f"{uri}/pregame").json()["state"] == "sealed"
            assert client.get(f"{uri}/full").status_code == 409
            verdict = client.get(f"{uri}/watchability").json()
            assert verdict["watchability_verdict"] == "Worth it"
            assert "home_score" not in verdict
            why = client.get(f"{uri}/why").json()
            assert why["watchability_reason"] == "Late run"
            full = client.post(f"{uri}/reveal")
            assert full.status_code == 200
            assert full.json()["home_score"] == 110
            assert client.get(f"{uri}/full").json()["home_score"] == 110
            assert client.post(f"{uri}/reveal").json() == full.json()
            assert client.get(f"/profiles/{profile}/games/{uuid4()}/pregame").status_code == 404
    finally:
        app.dependency_overrides.clear()


class FakeDisclosureScores:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def postgame_scores_as_of(self, game_ids, *, as_of):
        self.calls.append((game_ids, as_of))
        return self.rows


def archived_score(*, game_id=GAME_ID, at=FINAL, value=0.9):
    from nba_time_machine.ranking.scoring import FeatureObservation, PostgameSignal, score_postgame
    return score_postgame(
        game_id, {PostgameSignal.CLUTCH: FeatureObservation(value, "source:fact", at, at)},
        final_at=FINAL, as_of=at,
    )


def archived_disclosure(rows):
    from nba_time_machine.ranking.disclosure import VerdictBands
    original = snapshot()
    clock = FakeTimeline(cursor=FINAL)
    scores = FakeDisclosureScores(rows)
    acks = FakeAcks()
    service = GameDisclosureService(
        clock, FakeGames(original), acks, scores=scores,
        verdict_bands=VerdictBands(4, 7, "Low", "Medium", "High"),
    )
    return service, clock, scores, acks


@pytest.mark.asyncio
async def test_archived_verdict_is_coarse_explicit_and_does_not_fabricate_reasons():
    service, clock, scores, acks = archived_disclosure((archived_score(),))
    profile = uuid4()
    await service.disclose(profile, GAME_ID, DisclosureLayer.PREGAME)
    assert scores.calls == []
    result = await service.disclose(profile, GAME_ID, DisclosureLayer.WATCHABILITY)
    assert result.projection.fields == {"home_team": "Home", "away_team": "Away",
                                       "scheduled_tip": TIP.isoformat(), "watchability_verdict": "High"}
    why = await service.disclose(profile, GAME_ID, DisclosureLayer.WHY)
    assert why.projection.fields == result.projection.fields
    assert scores.calls == [((GAME_ID,), FINAL), ((GAME_ID,), FINAL)]
    assert not acks.rows
    assert clock.cursor == FINAL
    await service.reveal_full(profile, GAME_ID)
    await service.disclose(profile, GAME_ID, DisclosureLayer.FULL)
    assert len(scores.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "duplicate", "corrupt", "future", "wrong_game", "pregame"])
async def test_unusable_archive_never_falls_back_to_snapshot_hints(case):
    from dataclasses import replace
    from nba_time_machine.ranking.scoring import FeatureObservation, PregameSignal, score_pregame
    good = archived_score()
    rows = {
        "missing": (), "duplicate": (good, good),
        "corrupt": (replace(good, value=0.1),),
        "future": (archived_score(at=FINAL + timedelta(days=1)),),
        "wrong_game": (archived_score(game_id=uuid4()),),
        "pregame": (score_pregame(GAME_ID, {
            PregameSignal.TEAM_STRENGTH: FeatureObservation(0.9, "source:fact", CURSOR, CURSOR),
        }, tip_at=TIP, as_of=CURSOR),),
    }[case]
    service, _, _, acks = archived_disclosure(rows)
    for layer in (DisclosureLayer.WATCHABILITY, DisclosureLayer.WHY):
        fields = (await service.disclose(uuid4(), GAME_ID, layer)).projection.fields
        assert "watchability_verdict" not in fields
        assert "watchability_reason" not in fields
        assert "home_score" not in fields
    assert not acks.rows


def test_archive_backed_http_projection_never_serializes_score_or_components():
    service, _, _, _ = archived_disclosure((archived_score(),))
    app.dependency_overrides[get_game_disclosure_service] = lambda: service
    try:
        with TestClient(app) as client:
            uri = f"/profiles/{uuid4()}/games/{GAME_ID}"
            assert client.get(uri + "/watchability").json() == {
                "game_id": str(GAME_ID), "disclosure": "watchability", "watchability_verdict": "High",
            }
            assert client.get(uri + "/why").json() == {
                "game_id": str(GAME_ID), "disclosure": "why", "watchability_verdict": "High",
            }
    finally:
        app.dependency_overrides.clear()


def test_verdict_bands_are_configurable_and_invalid_configuration_fails(monkeypatch):
    from nba_time_machine.ranking.config import RankingDisclosureSettings
    monkeypatch.setenv("RANKING_VERDICT_MEDIUM_FROM", "2")
    monkeypatch.setenv("RANKING_VERDICT_HIGH_FROM", "5")
    monkeypatch.setenv("RANKING_VERDICT_HIGH_LABEL", "Try this game")
    bands = RankingDisclosureSettings().bands()
    assert bands.medium_from == 2 and bands.high_from == 5
    assert bands.high_label == "Try this game"
    monkeypatch.setenv("RANKING_VERDICT_MEDIUM_FROM", "6")
    with pytest.raises(ValueError):
        RankingDisclosureSettings().bands()
