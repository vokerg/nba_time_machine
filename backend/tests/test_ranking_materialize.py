"""Unit checks for the internal trusted-score materialization boundary."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nba_time_machine.ranking.materialize import RankingMaterializationService
from nba_time_machine.ranking.scoring import (
    FeatureObservation, PostgameSignal, PregameSignal, ScoreKind,
    score_postgame, score_pregame,
)

GAME = uuid4()
TIP = datetime(2026, 5, 5, 1, tzinfo=timezone.utc)
BEFORE = TIP - timedelta(hours=2)
FINAL = TIP + timedelta(hours=3)
AFTER = FINAL + timedelta(minutes=20)


def pregame():
    return score_pregame(
        GAME,
        {PregameSignal.EXPECTED_CLOSENESS:
         FeatureObservation(.4, "provider:before-tip", BEFORE, BEFORE)},
        tip_at=TIP, as_of=BEFORE,
    )


def postgame():
    return score_postgame(
        GAME,
        {PostgameSignal.COMEBACK:
         FeatureObservation(1.0, "provider:post-final", AFTER, AFTER)},
        final_at=FINAL, as_of=AFTER,
    )


class Evidence:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def pregame(self, game_id, *, as_of):
        self.calls.append(("pregame", game_id, as_of))
        return self.result

    async def postgame(self, game_id, *, as_of):
        self.calls.append(("postgame", game_id, as_of))
        return self.result


class Archive:
    def __init__(self):
        self.scores = []

    async def archive(self, score):
        self.scores.append(score)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "score,kind,cursor",
    [(pregame(), ScoreKind.PREGAME, BEFORE),
     (postgame(), ScoreKind.POSTGAME, AFTER)],
)
async def test_archives_only_selected_family_with_explicit_utc_cursor(score, kind, cursor):
    evidence, archive = Evidence(score), Archive()
    service = RankingMaterializationService(evidence, archive)
    shifted = cursor.astimezone(timezone(timedelta(hours=2)))
    assert await service.materialize(GAME, kind=kind, as_of=shifted) is True
    assert evidence.calls == [(kind.value, GAME, cursor)]
    assert archive.scores == [score]


@pytest.mark.asyncio
async def test_absent_trusted_evidence_does_not_write_or_fallback():
    evidence, archive = Evidence(None), Archive()
    result = await RankingMaterializationService(evidence, archive).materialize(
        GAME, kind=ScoreKind.POSTGAME, as_of=AFTER,
    )
    assert result is False
    assert evidence.calls == [("postgame", GAME, AFTER)]
    assert archive.scores == []


@pytest.mark.asyncio
@pytest.mark.parametrize("game_id,kind,as_of", [
    ("not-a-uuid", ScoreKind.PREGAME, BEFORE),
    (GAME, "postgame", AFTER),
    (GAME, ScoreKind.PREGAME, BEFORE.replace(tzinfo=None)),
    (GAME, ScoreKind.POSTGAME, None),
])
async def test_invalid_input_is_rejected_before_reading_evidence(game_id, kind, as_of):
    evidence, archive = Evidence(pregame()), Archive()
    with pytest.raises(ValueError):
        await RankingMaterializationService(evidence, archive).materialize(
            game_id, kind=kind, as_of=as_of,
        )
    assert evidence.calls == []
    assert archive.scores == []


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", [
    lambda score: replace(score, game_id=uuid4()),
    lambda score: replace(score, kind=ScoreKind.PREGAME),
    lambda score: replace(score, model_version="unreviewed"),
    lambda score: replace(score, as_of=AFTER + timedelta(seconds=1)),
    lambda score: replace(
        score, components=(
            replace(score.components[0], observed_at=AFTER + timedelta(hours=1)),
        ),
    ),
])
async def test_unexpected_postgame_reader_output_fails_closed(wrong):
    evidence, archive = Evidence(wrong(postgame())), Archive()
    with pytest.raises(ValueError, match="inconsistent evidence"):
        await RankingMaterializationService(evidence, archive).materialize(
            GAME, kind=ScoreKind.POSTGAME, as_of=AFTER,
        )
    assert archive.scores == []


@pytest.mark.asyncio
async def test_archive_error_is_not_relabelled_as_no_evidence():
    class FailingArchive:
        async def archive(self, score):
            raise ValueError("ranking revision collision")

    with pytest.raises(ValueError, match="collision"):
        await RankingMaterializationService(Evidence(postgame()), FailingArchive()).materialize(
            GAME, kind=ScoreKind.POSTGAME, as_of=AFTER,
        )
