"""Launch the separate local scoring workbench against the configured database."""
import argparse
import os
from pathlib import Path

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    os.chdir(Path(__file__).resolve().parents[1])
    print(f"Scoring workbench: http://127.0.0.1:{args.port} (production ratings, explicit collection/publication, configured Ringer auto-checks)")
    uvicorn.run("nba_time_machine.workbench.app:app", host="127.0.0.1", port=args.port,
                proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
