from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

BASE_URL = "https://www.thesportsdb.com/api/v1/json"
NBA_LEAGUE_ID = "4387"


async def _get(
    client: httpx.AsyncClient,
    api_key: str,
    endpoint: str,
    **params: str,
) -> dict[str, Any]:
    response = await client.get(
        f"{BASE_URL}/{api_key}/{endpoint}",
        params=params,
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{endpoint} returned a non-object JSON payload")
    return payload


async def main() -> None:
    api_key = os.getenv("THESPORTSDB_API_KEY", "123")

    async with httpx.AsyncClient() as client:
        next_payload = await _get(
            client,
            api_key,
            "eventsnextleague.php",
            id=NBA_LEAGUE_ID,
        )
        events = next_payload.get("events") or []
        if not events:
            raise RuntimeError("TheSportsDB NBA next-event response contained no events")

        event = events[0]
        required_event_fields = {
            "idEvent",
            "idLeague",
            "idHomeTeam",
            "idAwayTeam",
            "strEvent",
            "dateEvent",
        }
        missing = sorted(required_event_fields - set(event))
        if missing:
            raise RuntimeError(f"NBA event is missing expected fields: {missing}")

        if str(event["idLeague"]) != NBA_LEAGUE_ID:
            raise RuntimeError(
                f"Expected NBA league {NBA_LEAGUE_ID}, got {event['idLeague']}"
            )

        team_payload = await _get(
            client,
            api_key,
            "lookupteam.php",
            id=str(event["idHomeTeam"]),
        )
        teams = team_payload.get("teams") or []
        if not teams or not teams[0].get("idTeam"):
            raise RuntimeError("TheSportsDB home-team lookup returned no team")

        previous_payload = await _get(
            client,
            api_key,
            "eventspastleague.php",
            id=NBA_LEAGUE_ID,
        )
        previous_events = previous_payload.get("events") or []

        summary = {
            "provider": "thesportsdb",
            "league_id": NBA_LEAGUE_ID,
            "next_event": {
                "id": event.get("idEvent"),
                "name": event.get("strEvent"),
                "date": event.get("dateEvent"),
                "timestamp": event.get("strTimestamp"),
                "status": event.get("strStatus"),
                "home_team_id": event.get("idHomeTeam"),
                "away_team_id": event.get("idAwayTeam"),
            },
            "home_team": {
                "id": teams[0].get("idTeam"),
                "name": teams[0].get("strTeam"),
                "league": teams[0].get("strLeague"),
            },
            "previous_event_count": len(previous_events),
            "event_fields": sorted(event.keys()),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
