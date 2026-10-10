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
    assert not acks.rows

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
