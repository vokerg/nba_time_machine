#!/usr/bin/env python3
"""Operator-only #82 health smoke; one game, <=3 requests, no raw retention.

Uses the unchanged #80 probe. Redirects, credentials and retries are disabled.
Output is access/shape metadata, never source plays, players or scores.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from probe_nba_pbp import GAME_ID, target_url

PROBE_DEADLINE_SECONDS = 12

FAMILIES = {
    "live": ["trajectory"],
    "stats": ["trajectory"],
    "boxscore": ["context", "participation", "achievements"],
}


def sample(game_id: str, source: str) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    # A subprocess deadline bounds slow/drip-fed bodies as well as socket waits.
    # Validate before launching; callers cannot expand the endpoint allowlist.
    endpoint = target_url(game_id, source)
    if source not in FAMILIES:
        raise ValueError("unsupported source")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("probe_nba_pbp.py")),
             "--game-id", game_id, "--source", source],
            capture_output=True, text=True, timeout=PROBE_DEADLINE_SECONDS, check=True,
        )
        result = json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        result = {"game_id": game_id, "source": source, "endpoint": endpoint,
                  "error": "process_deadline"}
    except (subprocess.CalledProcessError, ValueError, OSError):
        # Never print child stderr/stdout, which is not a trusted log contract.
        result = {"game_id": game_id, "source": source, "endpoint": endpoint,
                  "error": "probe_execution_error"}
    return {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "environment": "operator_backend",
        "probe_deadline_seconds": PROBE_DEADLINE_SECONDS,
        "authentication": "none",
        "families_to_investigate": FAMILIES[source],
        "access": result,
        # Structural shape is insufficient for any evidence admission.
        "usable_normalized_games": 0,
        "coverage": "not_validated" if "shape" in result else "missing",
        "canonical_identity_verified": False,
        "pregame_availability_verified": False,
        "trusted_final_at_established": False,
        "retention": "diagnostic_metadata_only",
        "permission": "production_unresolved",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--source", choices=(*FAMILIES, "all"), required=True)
    args = parser.parse_args()
    if not GAME_ID.fullmatch(args.game_id):
        parser.error("game-id must be exactly ten decimal digits")
    for source in FAMILIES if args.source == "all" else (args.source,):
        print(json.dumps(sample(args.game_id, source), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
