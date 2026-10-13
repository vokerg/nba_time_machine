"""Local launcher checks; no application services or network needed."""

import importlib.util
from pathlib import Path
import select
import subprocess
import sys
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location("dev_launcher", Path(__file__).resolve().parents[2] / "dev.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_commands_use_local_venv_and_service_directories(tmp_path, monkeypatch):
    python = tmp_path / "backend/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    vite = tmp_path / "frontend/node_modules/.bin/vite"
    vite.parent.mkdir(parents=True)
    vite.touch()
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/npm")
    check = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher.subprocess, "run", check)
    backend, frontend = launcher.commands(tmp_path)
    assert backend[1] == [str(python), "-m", "uvicorn", "nba_time_machine.main:app", "--reload"]
    assert backend[2] == tmp_path / "backend"
    assert frontend[1:] == (["/usr/bin/npm", "run", "dev"], tmp_path / "frontend")
    assert check.call_args.kwargs["cwd"] == tmp_path / "backend"


def test_missing_npm_has_setup_instruction(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Install Node.js/npm"):
        launcher.commands()


def test_missing_frontend_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/npm")
    with pytest.raises(RuntimeError, match="npm install"):
        launcher.commands(tmp_path)


def test_missing_backend_dependencies(tmp_path, monkeypatch):
    vite = tmp_path / "frontend/node_modules/.bin/vite"
    vite.parent.mkdir(parents=True)
    vite.touch()
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/usr/bin/npm")
    check = Mock(return_value=Mock(returncode=1))
    monkeypatch.setattr(launcher.subprocess, "run", check)
    with pytest.raises(RuntimeError, match="README backend setup"):
        launcher.commands(tmp_path)
    assert check.call_args.args[0][0] == sys.executable


@pytest.mark.parametrize("exit_code", [0, 7])
def test_service_exit_stops_both(exit_code, monkeypatch):
    services = [("Backend", ["backend"], "/backend"), ("Frontend", ["frontend"], "/frontend")]
    monkeypatch.setattr(launcher, "commands", lambda: services)
    processes = [Mock(), Mock()]
    processes[0].poll.return_value = exit_code
    spawn = Mock(side_effect=processes)
    cleanup = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher.signal, "signal", Mock())
    monkeypatch.setattr(launcher, "stop", cleanup)
    assert launcher.main() == exit_code
    cleanup.assert_called_once_with(processes)
    assert all(call.kwargs["start_new_session"] for call in spawn.call_args_list)


def test_interrupt_stops_started_service(monkeypatch):
    monkeypatch.setattr(launcher, "commands", lambda: [("Backend", [], "/"), ("Frontend", [], "/")])
    process = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(side_effect=[process, KeyboardInterrupt]))
    monkeypatch.setattr(launcher.signal, "signal", Mock())
    cleanup = Mock()
    monkeypatch.setattr(launcher, "stop", cleanup)
    assert launcher.main() == 130
    cleanup.assert_called_once_with([process])


def test_cleanup_stops_descendants_after_parent_exits():
    # The child inherits stdout; EOF proves cleanup reached the descendant even
    # after the service parent exited (as can happen with npm/reload processes).
    child_code = "import time; print('ready', flush=True); time.sleep(60)"
    parent_code = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child_code!r}])"
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code], stdout=subprocess.PIPE, start_new_session=True,
    )
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline() == b"ready\n"
        process.wait(timeout=5)
        launcher.stop([process])
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.read() == b""
    finally:
        launcher.stop([process])
        process.stdout.close()
