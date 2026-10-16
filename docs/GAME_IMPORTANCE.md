# Legacy v3 reconstructed standings comparison (#96)

The default is now [game-supplied records, schema 4](GAME_RECORD_IMPORTANCE.md).
No history reconstruction is required for that path. Explicitly importing the
earlier schema-3 config retains this comparison mode.

The local workbench's legacy schema-3 proposal adds an editable **game-importance
bonus** to the existing drama, player and extreme-pattern contributions. Current
app scores and strict pregame ranking are unchanged. This is a transparent
heuristic for tuning, not a prediction of playoff outcomes.

## History and temporal boundary

The first reviewed calendar is the **2025–26 NBA regular season**, October 21,
2025 through April 12, 2026. Calendar source: [NBA schedule release](https://pr.nba.com/2025-26-nba-regular-season-schedule/).
Conference membership is a versioned 15 East / 15 West mapping of the shared
canonical team abbreviations, restricted to this season. Unsupported seasons,
preseason and playoff games explicitly lack this context.

Records are reconstructed from the season opener through **the previous Eastern
NBA day**. All games on the selected day, including the target game, and all later
games are excluded. This is an opening-day context snapshot, not an intraday
standings feed. Only final regular-season results count; preseason, postseason,
postponed/canceled games and the NBA Cup Championship are excluded. ESPN labels
the Cup final as season type 2 with competition type 39; the parser excludes
that combination. The [NBA Cup contract](https://api-hub.nba.com/news/nba-cup-101)
confirms its championship does not count toward regular-season records.

This data is collected **now**. Capture, observation and availability timestamps
stay at actual collection time; publication and trusted historical final times
are unknown. A historical game date is not an availability timestamp. The
workbench says **reconstructed later**, never verified pre-tip knowledge. No
`ranking.pregame.*` facts, consumer routes, hints or AI context are produced.

## Collector contract

From `backend/`:

```bash
# Bounded, live diagnostics; no DB connection or writes by default.
.venv/bin/python scripts/collect_standings_history.py --date 2025-11-10
# Explicit owner-authorized persistence, using the existing reviewed registry.
.venv/bin/python scripts/collect_standings_history.py --date 2025-11-10 --write --manual
```

- Access: existing fixed HTTPS ESPN NBA scoreboard endpoint, one `dates=YYYYMMDD`
  request per day; no auth, redirects, link following, article/prose collection
  or current standings endpoint. Generic RSS collectors do not dispatch this CLI.
- Cadence: explicit manual chunks or a future daily job. No scheduler or source
  activation is installed. `--manual` allows the reviewed disabled source for
  this invocation; it never overrides verification/auth/retention.
- Bounds: default 40 requests, explicit maximum 100, one-second spacing, 20-second
  deadline and 4-MiB decoded-body cap. There are no retries; 401/403/429 stops that
  host's later network calls. Use `--start YYYY-MM-DD` and multiple nonoverlapping
  chunks for longer history. Every day from the opener is still required at read.
- Identity: source `espn-nba-games`, logical capture `standings-day:YYYY-MM-DD`,
  results keyed by ESPN event ID and normalized day. Same content is idempotent;
  corrections append revisions, including reversions. Per-day failures stay
  visible and do not discard unrelated good days.
- Retention: `normalized_full` only; selected event ID, tip, teams and final
  scores plus coverage/exclusion/error counts. No original JSON, prose, HTML,
  media or credentials are retained. Representative source-shaped fixtures:
  `backend/tests/history_fixtures.py`.
- Persistence: existing raw captures/source items, collection runs/outcomes and
  season-linked `provider_regular_season_day_v1` temporal facts. The shared sports
  advisory lock serializes writes; the source policy is checked before requests
  and rechecked under a row lock per write. No new tables or alternate database.
- Completeness means internally valid **provider day coverage**, not an independent
  audit of ESPN's schedule. Every requested day requires a verified NBA response;
  an empty valid scoreboard differs from a failed fetch. New failed/invalid day
  coverage masks older snapshots. Reports expose attempted/usable days, result
  counts, writes, persistence failures and source outcomes without source bodies.

The reader selects the newest known revision for each required day before
validating it. Missing days, invalid latest data, same-time competing revisions,
expired facts, duplicate event IDs, impossible totals or revoked source approval
withhold importance. Future captures cannot enter an earlier evidence cutoff.
Zero bonus means the available measurements earn zero; absent context is null.

## Records, ranks and formulas

The workbench exposes each team's earlier wins/losses, games played, raw win%,
shared conference/league rank, all 30 teams, input event IDs and per-day fact IDs,
source URLs and observation/availability timestamps. Ranks use exact win ratios:
`1 + number of teams with strictly higher win%`. Ties share rank; alphabetical
display order within ties is not an official seeding tiebreaker. Zero-game teams
have unknown win%/rank. More than 82 counted results per team fails validation.

All settings below are editable and versioned in
`config/ranking/entertainment-context-v3.json`. `clamp` limits to 0–1; `ramp(x,a,b)`
is `clamp((x-a)/(b-a))`.

| Input or term | Default calculation |
| --- | --- |
| Minimum sample | At least 3 earlier games for both teams; otherwise unavailable |
| Smoothed win% | `(wins + 10/2) / (games played + 10)`; 10 neutral prior games |
| Both teams strong | Minimum of their smoothed-win% ramps from .50 to .75 |
| Both teams leaders | Minimum of `clamp((6 - shared conference rank) / (6 - 1))` |
| Sample confidence | `clamp(min(team games played) / 20)` |
| Matchup magnitude | `max(strong-team magnitude, leader magnitude) × confidence` |
| Standings gap | Absolute difference in teams' `(wins - losses)`, divided by 2 |
| Closeness | `clamp(1 - standings gap / 3)` |
| Late-season progress | Ramp smaller team games-played from 50 to 78 |
| Boundary proximity | `clamp(1 - minimum gap to a shared-rank 6th/10th boundary / 3)` |
| Race proxy | Same conference × closeness × late-season progress × boundary proximity |
| Importance bonus | `2 × max(matchup magnitude, race proxy)` |

Boundary membership includes every tied team whose shared-rank interval spans
6th or 10th; it does not invent official seeding. The race term is a heuristic
for nearby teams later in the season, **not** playoff odds, elimination,
clinching, actual leverage or an official games-behind table. Correlated matchup
and race terms combine by maximum. Strong-team and leader terms likewise are
not added twice. November games receive no late-season race credit by default.

Schema 3 adds `context` settings and a nullable importance contribution. The
proposed total is `min(10, drama + player + patterns + available importance)`;
uncapped sum, cap/rounding adjustments and missing families remain explicit.
Schemas 1/2 retain their prior formulas and import/export support. Inspectable
context on a legacy formula is labeled as excluded. Adoption into the consumer
app requires a separate reviewed change; no existing score archive is rewritten.


## Verification and owner-authorized operation

All **430 backend tests** passed on fresh disposable PostgreSQL, including
coverage gaps, future cutoffs, idempotent capture replay, invalid/expired/tied
newer revisions, source revocation and in-flight policy changes, read-only
v3 HTTP inspection, unchanged archives and legacy configs. Eight workbench DOM
tests passed, including schema-3 settings/percentage conversion and imports that
drop context when returning to v2. The first local suite and an isolated launcher
rerun hit the existing macOS process-group PermissionError; the final fresh full
suite passed. No launcher change is included.

Owner-authorized collection on October 15, 2026 fetched the 20 days from October
21 through November 9, 2025: **147 results, 20 normalized captures, zero errors**.
The real November 10 workbench has nine context-complete games and eight complete
proposed scores; Atlanta–Clippers remains withheld for its separate partial PBP.
Live inspection reconciled all contribution/cap arithmetic and reproduced the
original archived ratings. Fact/score counts did not change during inspection.
November race terms are zero under the default late-season thresholds. Calendar
and timestamps remain separate; nothing was backdated or activated in the
consumer app. Sanitized [operation evidence](evidence/game-importance-2025-11-10.json)
contains counts and checks, no full results or ratings.
