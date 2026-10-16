"""Launch the separate operator dashboard (not the consumer or scoring workbench)."""
import argparse
import os
from pathlib import Path

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    os.chdir(Path(__file__).resolve().parents[1])
    print(f"NBA coverage (read only): http://127.0.0.1:{args.port}")
    uvicorn.run("nba_time_machine.operator.app:app", host="127.0.0.1",
                port=args.port, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
