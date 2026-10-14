# NBA collection (#73)

`backend/scripts/collect_nba.py` uses the existing TheSportsDB client, structured
sports store and retention-enforcing capture store. It performs additive writes
against the configured database; it never migrates, deletes, resets or changes
credentials. Do not run integration tests against the owner's Neon database.

For fresh morning-after PBP/player statistics, use the separate bounded
[morning collection command](NBA_MORNING_COLLECTION.md) added in #84. It uses
ESPN first and CBS partial backup through the same capture/identity/temporal
tables; this TheSportsDB season command is unchanged.

From `backend/`:

```bash
.venv/bin/python scripts/collect_nba.py --season 2025-2026 --start 2025-10-01 --end 2026-06-30 --manual --report /tmp/nba-backfill.json
.venv/bin/python scripts/collect_nba.py --season 2026-2027 --start 2026-10-20 --end 2026-10-27 --manual --statistics
```

Every invocation fetches the season schedule, optionally followed by an inclusive
UTC/provider date window. This covers regular-season and playoff dates without
inventing phase labels from round numbers (which can also encode preseason).
It imports all returned season-matching events, including preseason if returned.
Use `--statistics` to request each event's available statistics. Normalized stat
fields, including supplied player/team identifiers, remain game-linked temporal
facts; these are not claimed to be validated player box scores. Current team
rosters and player career aggregates cannot establish historical game participation
and are not imported as historical rosters or game statistics.

Access is documented v1 REST with a backend-only API key. Settings read existing
`.env` and environment variables; environment variables take precedence. Sources
must be registry-verified with full/normalized-full structured-data retention.
Scheduled invocations require `enabled=true`. `--manual` explicitly authorizes an
operator invocation of the existing verified source while leaving scheduling
configuration unchanged. Source policy is rechecked under row lock before writes.
A transaction advisory lock prevents overlapping collector jobs; the dedicated
connection is kept active before each request and released on session close. Production schedulers
can invoke the same CLI with bounded `--max-requests` (default 400); no daemon or
scheduler is installed. Suggested cadence: daily full schedule refresh, and bounded
current-date polling during games; v1 offers no real-time SLA.

Provider event/team IDs map to stable internal UUIDs. A hash of the normalized
capture deduplicates identical repeats, preserving the first observation. Changed
schedule/status/score snapshots append history. Every capture and fact records its
actual collection time; availability equals observation. Publication, actual-tip
and final timestamps remain unknown. Fetching old games never creates a pre-tip
snapshot. Collection reports persist in collection runs/source outcomes, including
failed fetches, rejected events, empty stats and suspected truncation. A partial
outcome is deliberate: completeness requires an independent season manifest.

Requests are sequential and paced at least 2.1 seconds apart. Each request uses
the client's bounded timeout/retries, with no raw URL/key logging. Failed daily
fetches do not discard successfully committed days. A request budget bounds the
run; inspect the report and rerun remaining windows (failed earlier dates also
need retry). Repeating the entire window is safe. Normalized-full retention stores
normalized JSON text, hashes and timestamps, no raw provider response or artwork.
Full retention additionally allows raw JSON; third-party artwork is never fetched.
Representative mocked event/stat fixtures live in
`backend/tests/integration/test_sports_collection_persistence.py`.

## Provider coverage and additional requirements

Verified against the [API guide](https://www.thesportsdb.com/docs_api_guide),
[pricing](https://www.thesportsdb.com/docs_pricing) and
[terms](https://www.thesportsdb.com/docs_terms_of_use.php) on 2026-10-13:

- Public development key: season response limited to 15, daily to 3, event stats
  to 5. No documented pagination. A full response is suspected truncation.
- Premium raises season/day limits; a non-public key alone does not prove
  completeness. Reconcile regular season and playoffs against an authoritative
  season manifest before calling a backfill complete.
- Premium v2 supplies live scores. V1 imports observed live states when supplied
  but cannot promise timely updates. Production publication requires an appropriate
  subscription under provider terms.
- NBA standings are unsupported by the soccer-only table endpoint. Statistics,
  lineup, postseason and historical schedule availability coverage need verification.
- A documented licensed second provider (e.g. BALLDONTLIE after credentials/tier
  review) is required for missing games, player game box scores and standings.
  Historical replay additionally requires trustworthy historical publication or
  archived pre-tip snapshots. Do not backdate today's response to tip-off.

The owner key currently equals public development key `123`. The initial live
season smoke returned 15 2025-2026 events, starting with a preseason game; its
sampled event-stat lookup returned zero rows. This is evidence of working partial
access, not a complete NBA regular-season/playoff import. Live run reports and
exact imported counts are recorded on the PR. Complete-season acceptance remains
blocked on broader provider coverage and independent reconciliation.

## Observed Neon backfill evidence

The additive 2025/26 date pass completed 2025-10-01 through 2026-06-30 on
2026-10-13: 274 requests, 625 event rows encountered, 612 distinct games
processed, 597 new observations after the initial 15-event import, no rejected
events and no provider-request failures. The source report records 183 response
limit hits. These counts include provider-returned preseason events and do not
establish complete regular-season or playoff coverage. The 15 separately sampled
event-stat responses were all empty. See the sanitized persisted
[coverage report](evidence/nba-2025-26-coverage.json).

The first long-running CLI reported a failure during cleanup after its final
report had already committed. The collector now uses a transaction advisory lock
with connection keepalive before requests and automatic release on session close;
repeat/recovery writes are still idempotent. Check persisted run/outcome state
before restarting after an interruption.

The 2026/27 season plus 2026-10-13–2026-10-27 incremental smoke stored 53 games
and observations in 69 requests with zero rejected events or fetch failures. All
53 event-stat responses were empty. Repeating the same window used 16 requests
and wrote **zero** observations or captures; source reports remain partial because
13 response limits were reached. Sanitized [incremental](evidence/nba-2026-27-incremental.json)
and [replay](evidence/nba-2026-27-replay.json) reports are retained for review.
This verifies repeat collection and persistence, not live scoring latency or full
2026/27 schedule coverage. All database credentials were left unchanged; no
production migrations, deletes or integration tests were performed.

A later 2025/26 season-only replay returned just 5 rows (despite the earlier
15-row response), with zero new observations/captures. This reinforces that even
short responses cannot establish completeness. The
[season-only replay](evidence/nba-2025-26-season-replay.json) verifies only returned
records; it is not a repeat of the entire 273-day pass.
