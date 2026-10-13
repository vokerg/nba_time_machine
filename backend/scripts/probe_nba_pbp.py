#!/usr/bin/env python3
"""Manual, bounded research probe for Issue #80. NOT a collector.

No persistence, credential use, scraping, redirects, bypasses, or score output.
Intended for explicit operator invocation from the actual backend environment.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 8
GAME_ID = re.compile(r"^[0-9]{10}$")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def target_url(game_id: str, source: str) -> str:
    if not GAME_ID.fullmatch(game_id):
        raise ValueError("game-id must be exactly ten decimal digits")
    if source == "live":
        return f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
    if source == "boxscore":
        return f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
    if source == "stats":
        return "https://stats.nba.com/stats/playbyplayv3?" + urlencode(
            {"GameID": game_id, "StartPeriod": 0, "EndPeriod": 0}
        )
    raise ValueError("unsupported source")


def _marker(action: dict, kind: str) -> bool:
    fields = " ".join(
        str(action.get(key) or "") for key in ("actionType", "subType", "descriptor")
    ).lower().replace("_", "").replace("-", "").replace(" ", "")
    return kind + "period" in fields or ("period" + kind) in fields


def structural_diagnostics(payload: object, game_id: str, source: str) -> dict:
    """Compute non-sensitive shape/coverage counts. Never return plays or scores."""
    if not isinstance(payload, dict):
        return {"schema": "invalid_root", "structurally_complete": False}
    game = payload.get("game")
    if not isinstance(game, dict):
        return {
            "schema": "no_game_object",
            "top_level_keys": sorted(str(k) for k in payload.keys())[:15],
            "structurally_complete": False,
        }
    if source == "boxscore":
        return {
            "schema": "boxscore_game",
            "game_id_matches": str(game.get("gameId")) == game_id,
            "game_status_type": type(game.get("gameStatus")).__name__,
            "structurally_complete": False,
        }
    actions = game.get("actions")
    if not isinstance(actions, list):
        return {"schema": "no_actions_array", "structurally_complete": False}
    valid = [a for a in actions if isinstance(a, dict)]
    periods = sorted({a["period"] for a in valid
                      if type(a.get("period")) is int and a["period"] >= 1})
    starts = sorted({a["period"] for a in valid if type(a.get("period")) is int
                     and _marker(a, "start")})
    ends = sorted({a["period"] for a in valid if type(a.get("period")) is int
                   and _marker(a, "end")})
    ids = [str(a["actionNumber"]) for a in valid if a.get("actionNumber") is not None]
    has_scores = sum(
        a.get("scoreHome") is not None and a.get("scoreAway") is not None
        for a in valid
    )
    has_clock = sum(isinstance(a.get("clock"), str) and bool(a["clock"]) for a in valid)
    all_periods = bool(periods) and periods == list(range(1, max(periods) + 1))
    # This is only an internal structural check. It does NOT validate score
    # totals, source licensing, authoritative terminal timestamps or revisions.
    markers = all_periods and set(periods).issubset(set(starts) & set(ends))
    return {
        "schema": "game_actions",
        "game_id_matches": str(game.get("gameId")) == game_id,
        "actions_count": len(actions),
        "non_object_actions": len(actions) - len(valid),
        "periods": periods,
        "period_starts_detected": starts,
        "period_ends_detected": ends,
        "action_ids_present": len(ids),
        "duplicate_action_ids": len(ids) - len(set(ids)),
        "actions_with_score_fields": has_scores,
        "actions_with_clock": has_clock,
        "structurally_complete": bool(
            game.get("gameId") == game_id and len(valid) > 0 and markers
            and len(valid) == len(actions) and has_scores == len(valid)
            and has_clock == len(valid) and len(ids) == len(valid)
            and len(ids) == len(set(ids))
        ),
        "independently_verified_complete": False,
        "trusted_final_at_established": False,
    }


def probe(game_id: str, source: str) -> dict:
    url = target_url(game_id, source)
    result: dict = {"game_id": game_id, "source": source, "endpoint": url,
                    "max_bytes": MAX_BYTES, "timeout_seconds": TIMEOUT_SECONDS}
    req = Request(url, headers={"Accept": "application/json",
                                "User-Agent": "nba-time-machine-readonly-research/1.0"})
    started = time.monotonic()
    try:
        with build_opener(NoRedirects).open(req, timeout=TIMEOUT_SECONDS) as resp:
            result["http_status"] = resp.status
            result["content_type"] = resp.headers.get("Content-Type", "")
            raw = resp.read(MAX_BYTES + 1)
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["bytes_read"] = len(raw)
        if len(raw) > MAX_BYTES:
            result["error"] = "response_too_large"
            return result
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            result["error"] = "invalid_json"
            return result
        result["shape"] = structural_diagnostics(payload, game_id, source)
    except HTTPError as exc:
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["http_status"] = exc.code
        result["error"] = "http_error"
        # Do not read or log potentially sensitive error-response bodies.
    except (URLError, TimeoutError, OSError) as exc:
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["error"] = "transport_error"
        result["transport_exception"] = type(exc).__name__
        # DNS/proxy failures are not HTTP 403 or evidence of server rejection.
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True, help="10-digit NBA game ID")
    parser.add_argument("--source", required=True, choices=("live", "stats", "boxscore", "all"))
    args = parser.parse_args()
    if not GAME_ID.fullmatch(args.game_id):
        parser.error("game-id must be exactly ten decimal digits")
    sources = ("live", "stats", "boxscore") if args.source == "all" else (args.source,)
    for src in sources:
        print(json.dumps(probe(args.game_id, src), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
