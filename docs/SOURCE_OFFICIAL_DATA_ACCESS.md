# Official NBA injury and transaction source access (Issue #9)

**Research date:** 2026-10-12. This is a source-discovery checkpoint, not
collector validation or authorization to store publisher content.

## Located league publication surfaces

| Registry ID | Canonical inspected page | Browser observation | Collector status |
| --- | --- | --- | --- |
| `nba-official-transactions` | https://www.nba.com/players/transactions | NBA's 2026 free-agency hub links to this player-transactions page, which has transaction/team/month filters; a direct text page read displayed `Loading Transactions...` rather than reliably extracted transaction rows | **Unverified**, disabled |
| `nba-official-injuries` | https://official.nba.com/nba-injury-report-2025-26-season/ | NBA Official published a 2025-26 season report page describing team reporting obligations and multiple daily updates; this is a *season-scoped publication index*, not a confirmed 2026-27 feed | **Unverified**, disabled |

Primary references:
- [NBA's free-agency hub linking to All NBA Transactions](https://www.nba.com/freeagents/2026/transactions)
- [NBA Player Transactions](https://www.nba.com/players/transactions)
- [NBA Official: 2025-26 injury report](https://official.nba.com/nba-injury-report-2025-26-season/)

## Access, rights and timestamps

**Transactions:** Public browser navigation exposed the official destination
without login in this research session. Direct text-page extraction did not
demonstrate a complete, machine-parseable transaction list, a stable per-event
ID, time-of-day, or immutable edit history. The observed filters and possible
client-side rendering do **not** establish a usable `web` collector:
the current adapter fetches only one configured page without JavaScript or
link traversal. Keep the 30-minute cadence as a **proposal**, not an active
schedule. Treat dates displayed on a later successful read as source claims,
not as proof that an item was available to a historical viewer then.

**Injuries:** The linked official page is explicitly for **2025-26**; it must
not be represented as a confirmed **2026-27** season publication source.
The page says reports are updated continually, but no PDF/link traversal,
record-level ID, revision history, schedule, stable report snapshots, or
2026-27 replacement has been validated in a bounded adapter run. The
15-minute cadence is a **proposal**, not an active collector. A PDF document
or linked report may require a *separate approved document adapter*;
the current `web` adapter is not evidence that it can parse PDF contents.

**Both entries:** They are public official publisher identities, not reviewed
API licenses, robots/crawl permission, contract rights or evidence of a
successful HTTP capture by NBA Time Machine. No authentication was required
for the browser text inspection, but this does not preclude endpoint-specific
authentication, rate limiting, blocks or redistribution restrictions.
Conservatively set `metadata_only` instead of the former unreviewed
`normalized_full` proposal; **nothing is collected or retained** while
`enabled=false`. These are separate sources from NBA.com news and TheSportsDB.
Future reconciliation must deduplicate overlapping factual claims without
collapsing original source identities.

For any future approved extraction, independently timestamp **first
observation** and **availability**, append corrections, and avoid backdating
from a displayed transaction/report date or from the season page's creation.
Historical as-of reads and pregame injury features must use only facts
actually known before the selected cursor and tip. No source page is itself
an authorization to expose game-specific facts or build AI inputs.

## Next validation steps

1. Independently locate and inspect the official **2026-27 injury-report**
   publication page when present; update the same stable source ID only after
   reviewing its current access method and explaining the season switch.
2. Check source-specific terms/robots/rate limits and permitted retention;
   do not infer content rights from publicly readable HTML.
3. Perform a bounded `web` adapter smoke for transactions and, separately,
   a properly scoped document/PDF extraction smoke if approved for injuries.
   Record status code, redirect/content type, item counts, stable IDs,
   timestamps, parsing/deduplication, and date of execution without logging
   player medical narratives or secrets.
4. Keep both disabled until an explicit activation decision. Mark an
   individual source **verified** only when the project's actual collector,
   data model and legal/access requirements have been checked.

This slice does not implement a collector, supply injury facts to ranking,
prove current-season coverage or touch live PostgreSQL/Neon.
