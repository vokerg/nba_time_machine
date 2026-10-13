#!/usr/bin/env python3
"""Start the local backend and frontend together (macOS/Linux)."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def commands(root=ROOT):
    python = root / "backend/.venv/bin/python"
    if not python.is_file():
        python = Path(sys.executable)
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("Install Node.js/npm, then run npm install in frontend/.")
    if not (root / "frontend/node_modules/.bin/vite").is_file():
        raise RuntimeError("Frontend dependencies are missing. Run: cd frontend && npm install")
    check = subprocess.run(
        [str(python), "-c", "import uvicorn, nba_time_machine"],
        cwd=root / "backend", capture_output=True,
    )
    if check.returncode:
        raise RuntimeError(
            'Backend dependencies are missing. Follow the README backend setup '
            '(create backend/.venv and pip install -e ".[dev]").'
        )
    return [
        ("Backend", [str(python), "-m", "uvicorn", "nba_time_machine.main:app", "--reload"], root / "backend"),
        ("Frontend", [npm, "run", "dev"], root / "frontend"),
    ]


def stop(processes):
    # Reloaders and npm spawn children: signal the entire session's process group.
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
        time.sleep(0.05)
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main():
    if os.name != "posix":
        print("This launcher supports macOS and Linux.", file=sys.stderr)
        return 1
    processes = []

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        services = commands()
        print("Starting backend and frontend. Press Ctrl+C to stop both.", flush=True)
        for name, command, cwd in services:
            processes.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
        while True:
            for (name, _, _), process in zip(services, processes):
                code = process.poll()
                if code is not None:
                    print(f"{name} exited ({code}); stopping both servers.", flush=True)
                    return code if code >= 0 else 128 - code
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping both servers.", flush=True)
        return 130
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        # A second Ctrl+C must not interrupt cleanup and leave children running.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop(processes)


if __name__ == "__main__":
    sys.exit(main())
