# Previous-season foundation for game importance (#122)

Early-season matchup strength uses the immediately previous completed season when
validated evidence exists. This is team/game importance, shared by pregame
expectation and the up-to-two-point postgame matchup contribution. It does not
change the exceptional game-pattern measurements or favorite-team handling.

Each team's starting rate is `(last-season wins + 5) / 92`. Verified Finals success
sets a floor of .750 for the champion and .680 for the finalist. No team is
hardcoded. The foundation begins at 20 equivalent games, with remaining strength
`k = 20 * max(0, 1 - current games / 40)`. Blended rate is
`(current wins + k * starting rate) / (current games + k)`. The prior's weight is
`k / (current games + k)`: 100% at opening, about 86% after three games, 60% after
ten, 33% after twenty, and zero from forty onward. Genuine complete prior evidence
permits ratings before the old three-game minimum; missing evidence retains the
existing current-season-only calculation rather than manufacturing a prior.

Team strength still ramps from zero at .500 to one at .750. With a prior, matchup
importance is `.4 * max(home, away) + .6 * sqrt(home * away)`. A single contender
therefore adds some importance, and two contenders add more. The bonus stays
bounded at two points; it is not a win probability or a claim about lineups.
Current W–L records shown on cards remain actual entering records.

Admin's saved record context includes last-season records, Finals achievement,
starting rate, blend weights, current results and original evidence references.
The public pregame projection retains its existing narrow fields and adds version
identifiers `pregame-records-v2` / `pregame-context-v3`. Postgame publications that
use the foundation use `postgame-season-strength-v5`; v4 and older scores remain
readable and immutable. Saved ratings never change on read or source collection.
Only explicit recalculation publishes a replacement snapshot.

## Source and collection contract

- Access: existing approved ESPN structured source `espn-nba-games`, HTTPS JSON
  season standings plus June NBA Finals scoreboard. Supported prior seasons:
  2024–25 and 2025–26 (82-game seasons, June Finals).
- Endpoints: `/apis/v2/sports/basketball/nba/standings?season=YEAR&seasontype=2`
  and `/apis/site/v2/sports/basketball/nba/scoreboard?dates=YEAR06&limit=100`.
- Authentication: none. Existing source verification and `normalized_full`
  retention approval are required before requests and checked again before writes.
- Cadence: only explicit **Fetch games & update ratings** calls collection. A
  valid stored foundation is reused for the season; failed attempts have a
  durable 24-hour cooldown. Recalculation from stored evidence never fetches.
- Limits: two requests, one-second pacing, twenty-second per-request timeout,
  four-MiB response limit, no retries; existing host-stop rules apply to
  authentication/rate-limit failures. Foundation failure does not stop games.
- Identity/deduplication: prior-season label plus canonical ESPN team ID and
  normalized NBA abbreviation; all thirty unique teams must have 82-game totals
  and league wins/losses must both total 1,230. Canonical team mappings are checked
  again when applying a foundation to a matchup. Normalized capture hash dedups.
- Title evidence: explicit NBA Finals round, matching season, completed final
  event, completed best-of-seven series, exactly one four-win team, and agreeing
  winner flag and final scores. Neither seeding nor summary prose establishes a
  title. An absent or conflicting completion withholds the foundation.
- Timestamps: actual capture time is both observation and availability. The
  provider's season-end boundary is retained as a conservative completed-season
  check, not claimed as the actual Finals finish. No timestamps are backdated.
- Retention: only normalized records, Finals achievement/event ID and boundary
  are retained through canonical raw-capture/temporal-fact tables; entire provider
  responses, images, URLs from untrusted bodies and prose are not retained.
- Persistence: `team_strength.season_foundation.v1` is a season temporal fact;
  collection runs and source outcomes record success/failure. No parallel store.
- Fixture: `tests/test_season_strength.py::payloads` contains synthetic complete
  standings and a reconciled Finals clincher, with rejection and decay cases.

Browse can use last-season evidence collected later, with actual timestamps and
an explicit reconstructed basis. Time Machine requires the foundation both known
by its cutoff and observed before the target tip. Both modes require that it is
exactly the immediately preceding season and that its season-end boundary is
before tip. Latest ambiguous, expired, malformed, wrong-team or revoked evidence
is omitted without resurrecting an older snapshot.

For an explicit foundation-only capture without recalculating ratings:

```bash
cd backend
.venv/bin/python scripts/collect_season_foundation.py --date 2026-10-27 --write
```

`--force` explicitly rechecks a previously saved foundation. Normal app reads
never collect. This optional CLI uses the same documented collection module.
