from __future__ import annotations

import asyncio
import json

from nba_time_machine.sports import SportsProviderSettings, TheSportsDBClient


async def main() -> None:
    settings = SportsProviderSettings()

    async with TheSportsDBClient(settings) as client:
        next_events = await client.next_nba_events()
        if not next_events:
            raise RuntimeError("TheSportsDB NBA next-event response contained no events")

        event = next_events[0]
        required_event_fields = {
            "idEvent",
            "idLeague",
            "idHomeTeam",
            "idAwayTeam",
            "strEvent",
            "dateEvent",
            "strTimestamp",
            "strStatus",
        }
        missing = sorted(required_event_fields - set(event))
        if missing:
            raise RuntimeError(f"NBA event is missing expected fields: {missing}")

        if str(event["idLeague"]) != settings.nba_league_id:
            raise RuntimeError(
                f"Expected NBA league {settings.nba_league_id}, got {event['idLeague']}"
            )

        team = await client.team(str(event["idHomeTeam"]))

        previous_events = await client.previous_nba_events()
        previous = previous_events[0] if previous_events else None
        stats = (
            await client.event_stats(str(previous["idEvent"]))
            if previous and previous.get("idEvent")
            else []
        )

        summary = {
            "provider": settings.provider,
            "league_id": settings.nba_league_id,
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
                "id": team.get("idTeam"),
                "name": team.get("strTeam"),
                "league": team.get("strLeague"),
            },
            "previous_event": (
                {
                    "id": previous.get("idEvent"),
                    "date": previous.get("dateEvent"),
                    "timestamp": previous.get("strTimestamp"),
                    "status": previous.get("strStatus"),
                    "home_score": previous.get("intHomeScore"),
                    "away_score": previous.get("intAwayScore"),
                }
                if previous
                else None
            ),
            "event_stat_count": len(stats),
            "first_event_stat": stats[0] if stats else None,
            "event_fields": sorted(event.keys()),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
