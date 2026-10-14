"""Offline, synthetic-only tests for the read-only issue #80 access probe."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_nba_pbp.py"
SPEC = importlib.util.spec_from_file_location("probe_nba_pbp", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
GAME_ID = "0042500311"


def synthetic_game(periods=4, omit_end=None):
    """Generated event-like records, NOT a real NBA payload or historical evidence."""
    actions = []
    number = 0
    for period in range(1, periods + 1):
        for marker, clock in (("startperiod", "PT12M00.00S"),
                              ("endperiod", "PT00M00.00S")):
            if marker == "endperiod" and period == omit_end:
                continue
            number += 1
            actions.append({
                "actionNumber": number,
                "period": period,
                "clock": clock,
                "scoreHome": str(number),
                "scoreAway": "0",
                "descriptor": marker,
            })
    return {"game": {"gameId": GAME_ID, "actions": actions}}


def test_four_period_markers_are_only_structural_not_trusted_final():
    result = probe.structural_diagnostics(synthetic_game(), GAME_ID, "live")
    assert result["periods"] == [1, 2, 3, 4]
    assert result["structurally_complete"] is True
    assert result["independently_verified_complete"] is False
    assert result["trusted_final_at_established"] is False


def test_double_overtime_recognized_without_presuming_final_time():
    result = probe.structural_diagnostics(synthetic_game(periods=6), GAME_ID, "live")
    assert result["periods"] == [1, 2, 3, 4, 5, 6]
    assert result["structurally_complete"] is True
    assert result["trusted_final_at_established"] is False


def test_missing_endmarker_fails_closed():
    result = probe.structural_diagnostics(synthetic_game(omit_end=4), GAME_ID, "live")
    assert result["structurally_complete"] is False
    assert result["period_ends_detected"] == [1, 2, 3]


def test_duplicate_action_identifier_fails_closed():
    payload = synthetic_game()
    payload["game"]["actions"][1]["actionNumber"] = 1
    result = probe.structural_diagnostics(payload, GAME_ID, "live")
    assert result["duplicate_action_ids"] == 1
    assert result["structurally_complete"] is False


def test_wrong_game_id_fails_closed():
    result = probe.structural_diagnostics(synthetic_game(), "0022500450", "live")
    assert result["game_id_matches"] is False
    assert result["structurally_complete"] is False


def test_boxscore_cannot_claim_complete_pbp_or_trusted_final():
    result = probe.structural_diagnostics({"game": {"gameId": GAME_ID,
                                                      "gameStatus": 3}}, GAME_ID, "boxscore")
    assert result["schema"] == "boxscore_game"
    assert result["structurally_complete"] is False


@pytest.mark.parametrize("bad", ["../../etc/passwd", "0022500002?x=1", "002250000", "ABCDEFGHIJ"])
def test_game_id_restricted_to_nba_identity(bad):
    with pytest.raises(ValueError):
        probe.target_url(bad, "live")


def test_source_is_allowlisted():
    with pytest.raises(ValueError):
        probe.target_url(GAME_ID, "other")


def test_valid_url_shapes():
    assert probe.target_url(GAME_ID, "live").endswith(
        "/playbyplay_0042500311.json"
    )
    assert "GameID=0042500311" in probe.target_url(GAME_ID, "stats")
