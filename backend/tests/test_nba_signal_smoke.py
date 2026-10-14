"""Synthetic child results only; never invokes a live source."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# The operator script imports its sibling, just as normal script execution does.
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("signal_smoke", SCRIPTS / "smoke_nba_signals.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
finally:
    sys.path.remove(str(SCRIPTS))


def test_each_source_is_independent_and_no_evidence_is_admitted(monkeypatch):
    calls = []

    def child(args, **kwargs):
        calls.append((args, kwargs))
        source = args[-1]
        return SimpleNamespace(stdout=json.dumps(
            {"source": source, "http_status": 403} if source == "live" else
            {"source": source, "http_status": 200, "shape": {"structurally_complete": True}}
        ))

    monkeypatch.setattr(smoke.subprocess, "run", child)
    results = [smoke.sample("0022500450", source) for source in smoke.FAMILIES]
    assert len(calls) == 3
    assert results[0]["coverage"] == "missing"
    assert results[1]["coverage"] == "not_validated"
    for result in results:
        assert result["usable_normalized_games"] == 0
        assert result["started_at"] <= result["completed_at"]
        assert not result["trusted_final_at_established"]
        assert not result["pregame_availability_verified"]
    assert all(kwargs["timeout"] == 12 and kwargs["capture_output"]
               for _, kwargs in calls)


@pytest.mark.parametrize("failure,expected", [
    (subprocess.TimeoutExpired("probe", 12, output="PRIVATE BODY"), "process_deadline"),
    (subprocess.CalledProcessError(1, "probe", stderr="PRIVATE BODY"), "probe_execution_error"),
    (OSError("PRIVATE BODY"), "probe_execution_error"),
])
def test_errors_do_not_leak_child_content(monkeypatch, failure, expected):
    def child(*args, **kwargs):
        raise failure
    monkeypatch.setattr(smoke.subprocess, "run", child)
    result = smoke.sample("0022500450", "live")
    assert result["access"]["error"] == expected
    assert "PRIVATE" not in json.dumps(result)
    assert result["coverage"] == "missing"


def test_invalid_targets_cannot_spawn_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid input launched child")
    monkeypatch.setattr(smoke.subprocess, "run", forbidden)
    for game, source in (("../../etc/passwd", "live"), ("0022500450", "espn")):
        with pytest.raises(ValueError):
            smoke.sample(game, source)
