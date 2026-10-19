# Experimental ranking-based Star Power (#98)

Star Power measures established player status multiplied by actual participation.
An unexpected exceptional performance still belongs exclusively to Player
Performance. This schema-5 workbench proposal preserves drama, player production,
extreme patterns, record-based importance and the overall ten-point cap. No
production score, archive, consumer endpoint, spoiler gate or scheduler changes.

## Default tuning policy: first snapshot for earlier games (schema 6)

The owner explicitly changed the historical tuning policy: games before the first
usable complete snapshot use that **first** snapshot as a retrospective assumption.
The default `entertainment-stars-backfill-v6.json` sets
`star_snapshot_policy: first_snapshot_backfill`. Schema 6 can also select
`strict_pre_tip`; schemas 1–5 and their saved exports keep their original behavior.

The reader first tries the normal latest eligible same-season pre-tip snapshot.
Only when none exists may this policy select the earliest complete snapshot known
by the report cutoff, provided the game tipped before that snapshot. Initial
incomplete identity captures are not usable; the first fully resolved revision
is selected. Later updates do not replace the first snapshot for older games.
Expiry, invalid signatures/schema, ambiguous timestamps and revoked source policy
still fail closed. The fallback can cross seasons, as explicitly requested for
all earlier games, and that cross-season assumption is displayed separately.

No timestamp, publication date, season, source fact or archived score is changed.
Reports add `selection_mode`, `retrospective`, `first_snapshot_at`, `game_season`
and `cross_season_assumption` metadata. The slate and selected-game details label
retrospective use; configuration and review exports preserve the explicit policy.
The pure extractor requires both the explicit policy and the reader's retrospective
selection metadata before accepting a post-tip/cross-season ranking. This is a
workbench-only approximation of reputation, not genuine historical availability.
Consumer/production scoring and spoiler access remain unchanged.

Real read-only verification on October 13, 2026: Cleveland at Orlando now has a
Star Power bonus of 0.8334 and proposed score 2.0934; only preseason game importance
is unavailable. November 10, 2025 WAS–DET uses the same first snapshot with an
explicit cross-season flag: Star Power bonus 0.4046, overall score still capped at
10. These are retrospective real-data tuning checks, not pre-tip historical
validation. The old strict v5 configuration still withholds both historical bonuses.

## Current private hobby operation (October 16, 2026)

The owner explicitly directed automated Ringer fetching for this private hobby
project, at most once per fourteen days. That supersedes the earlier manual-only
fallback. This is recorded as `access_basis: owner_directed_private_hobby`,
`publisher_permission: false`, and a legacy `permission_reference` whose value
explicitly says it is **not a publisher license**. Technical verification means
format/access validation; it does not certify legal rights. The linked terms
restriction found below remains acknowledged. No production or redistribution
permission is claimed.

Explicit one-time setup, from `backend/`:

```bash
.venv/bin/python scripts/collect_ringer_rankings.py --configure-private-hobby
```

After setup, the separately launched local scoring workbench checks whether the
source is due at startup and hourly while running. Its database reservation
allows only **one Ringer request per fourteen days**, including failures, crashes,
restarts and concurrent processes. It performs one fixed HTTPS GET, no redirects,
no retries, no cookies/login/proxies or access-control bypass; limits are 30-second
HTTP timeout, 45-second total collection limit and 4 MiB decoded response size.
403/429, challenges, changed layout and incomplete lists remain visible failures.
An identical captured list deduplicates; changes append versions in the canonical
capture/fact pipeline. There is no force-refresh flag. The checked-in source seed
remains unapproved/manual; the explicit setup changes only the runtime hobby source
and preserves its attempt cursor. Re-syncing the old seed can disable this runtime
mode and will require explicit setup again, without bypassing cadence.

`ingestion/ringer.py` parses one ordered list with exactly 100 player cards and
unique profile slugs. It retains only names, ranks, source slugs and provenance.
The page's labeled Updated date is date-only publication evidence; it never
backdates capture/availability. Season is inferred from the capture NBA year
(August turnover); this is documented applicability, not verified publisher season
metadata. Publisher prose/images and raw HTML are discarded. No full publisher
list is committed as a fixture or document.

Missing ESPN identities trigger a bounded current-roster identity pass through
`sports/player_identities.py`, under the existing reviewed ESPN source policy.
It fetches the NBA team index plus at most 30 roster endpoints (31 requests,
one second spacing, 20-second per-request timeout, 4 MiB per response). Team
abbreviations normalize through existing aliases; canonical teams resolve through
the existing sports store/lock. Independent teams commit normalized ID/name/team
captures and `provider_player_identities.espn-v1` team facts at actual observation
time. Roster membership never proves game participation, DNP or historic team
membership. Actual Star Power still uses the game's box rows. A roster check is
also bounded to fourteen days per collector version. The initial setup uncovered
and corrected team-alias/canonical-team integration errors; those failed runs
remain in health history. The successful v3 pass saved 30 rosters / 630 identities.

Stored incomplete rankings can be remapped from newly available identity evidence
without another Ringer request. Mapping revisions retain source content hashes and
get actual new observation timestamps; they never manufacture historical
eligibility. All 100 identities must resolve before the combined bonus is enabled.

The read-only `/api/ringer-status` endpoint and workbench status line expose
current readiness, matched count, snapshot-known timestamp, last network attempt,
next allowed request and latest collection error. There is no consumer route.
Failures retain the last valid snapshot as historical evidence; policy revocation
still withholds it. The worker runs only while the local workbench process runs;
a stopped/asleep computer does not collect missed historical snapshots. Restart
performs at most one due check. No system daemon/cloud deployment is installed.

Real verification: one Ringer request on October 16 at 07:46:41 UTC, 100 parsed
rows, 100 validated ESPN mappings after roster enrichment, publisher update label
October 14, 2026, complete snapshot known at 07:55:13 UTC. Next publisher request
is October 30 at 07:46:41 UTC. Parsing/publication metadata was refined from the
same in-memory initial response, without a second Ringer request. Initial partial
and mapping/publication revisions remain traceable. No archived scores changed.
October 13 games remain unavailable; October 16 scheduled games can use this
snapshot after final participation evidence is collected. Five actual future scheduled-game observations were checked against the snapshot
reader and all selected this complete pre-tip snapshot. A completed genuinely
eligible real-game scoring smoke must wait for such a game to finish; it has not
been fabricated. Tests cover scoring/participation with synthetic eligible games.

## Initial source review and manual-only fallback (historical context)

The [Ringer Top 100](https://www.theringer.com/nba-ranked/top-100) is readable as
an ordered list of 100 linked player cards. The page observed during this review
labels an October 14, 2026 update and describes monthly in-season updates. It
explicitly excludes long-term injured players until they play. Individual profile
URLs use name slugs; these are not ESPN IDs. Names, ranks and optional published
team/source identity can be imported; prose, images and full publisher HTML are
neither needed nor retained by this implementation. No documented licensed ranking
API or stable machine interface was established. This is page discovery and
format inspection, not a successful licensed ingestion smoke.

The site's footer links to [Spotify terms](https://www.spotify.com/us/legal/end-user-agreement/),
which limit access and content use and restrict redistribution. Public readability
does not establish permission to retain/reuse a whole ranking. The source seed
therefore remains **disabled, unverified, metadata-only**, without a permission
reference in the seed. The initial release had no network collector; the owner-directed hobby collector above now provides one. Manual import is an input mechanism,
not a way around these restrictions: obtain authorization covering private
normalized retention and use before reviewing the registry policy. Do not commit
or redistribute a publisher's full list or private permission records.

[ESPN NBArank](https://www.espn.com.sg/nba/story/_/id/46306892/nba-rank-2025-rankings-top-10-players-jokic-durant-lebron)
is a reference only. Its 2025 edition describes predicted contributions for a
single season and is split across ranked-range articles; no ongoing in-season
update promise was verified. The US article did not provide usable ranking text
in the reader; the regional ESPN reference did. [Disney terms](https://disneytermsofuse.com/english/)
restrict automated extraction and copying. No ESPN ranking importer or automatic
fallback is enabled, and the two editorial lists are never silently mixed.
Existing reviewed ESPN **game evidence** access remains a separate source policy.
Robots availability could not be established with the reader; no robots inference
or undocumented endpoint probing was used to grant access.

## Manual normalized snapshot import

The explicit entry point is `backend/scripts/import_player_rankings.py`. It reads
at most 256 KB of local JSON and never fetches a URL, changes source policy or
accepts observation/availability timestamp overrides. From `backend/`:

```bash
.venv/bin/python scripts/import_player_rankings.py /private/authorized-snapshot.json
.venv/bin/python scripts/import_player_rankings.py /private/authorized-snapshot.json --write
```

Default is validation/mapping diagnostics only. Both modes require an existing
`ringer-nba-top100-manual` registry source with the exact reviewed URL,
`manual_player_rankings` adapter, `verified` status, `normalized_full` (or `full`)
retention and nonempty `adapter_settings.permission_reference`. That reference
must match the file. `automated_access` must remain false. The importer is manual
and can run while the source is disabled; it cannot activate the generic scheduler.
Review policy using the existing registry workflow, not an importer flag.
A weekly manual review is recommended (seed cadence 10,080 minutes); no weekly
poller, due-check request or automatic schedule is installed.

The schema is `RankingImport` in `ranking/player_rankings.py`:

```json
{
  "schema_version": 1,
  "provider": "The Ringer",
  "ranking_version": "publisher-edition-label",
  "season": "2026-2027",
  "source_url": "https://www.theringer.com/nba-ranked/top-100",
  "publication_status": "publisher_date_only",
  "published_date": "2026-10-14",
  "publication_reference": "reviewed page or authorized edition reference",
  "permission_reference": "private authorization reference matching registry policy",
  "players": []
}
```

`players` must actually contain exactly 100 rows with unique ranks 1–100. Each
row requires integer `rank` and `name`, optionally `team` (canonical abbreviation),
`source_player_id`, `espn_id`, `espn_name_alias`, `alias_review`. The empty list
above is a schema illustration and intentionally cannot be imported. Unknown
publication uses `publication_status: "unknown"` and no date. Date-only publisher
claims are stored separately and **never establish historical availability**.
Future publication dates are rejected. No preexisting observation history is
asserted by importing an old edition today.

Identity matching uses namespaced ESPN IDs from retained, policy-approved game
box facts, bounded to 5,000 facts (overflow fails explicitly). The catalog retains
supporting fact IDs. Unicode accent/punctuation normalization supports e.g.
Jokić/Jokic; it does not remove generational suffixes, guess initials or perform
fuzzy matching. Unique normalized name plus published team disambiguates candidates;
without a published team, the name must be globally unique in the catalog.
An explicit ID must already have a matching observed name or an explicitly
reviewed alias. An ID validated this way survives a trade without claiming the
ranking's team is current. Team disagreements without an explicit ID stay
unmatched. Duplicate names/ID collisions remain ambiguous, never silently mapped.
Missing identities remain visible; all 100 must resolve before a combined bonus
is available. This conservative rule avoids assuming an unmatched player cannot
be relevant to either team. Expand approved game evidence or review an alias,
then import a mapping revision; never edit a prior fact.

## Persistence and temporal eligibility

No new tables or parallel store. Imports use existing collection runs, outcomes,
policy-limited normalized captures, source items and season-linked temporal facts
(`player_rankings.ringer-v1`). The captured payload is normalized source fields
plus reproducible identity mapping and proof references. Publication date/precision
are retained in the payload; capture/observation/availability use actual server
import time. A publisher content hash and a separate source-plus-mapping revision
hash distinguish changes. Supporting-proof growth alone does not duplicate an
identical mapping. Latest-identical imports record idle/no new capture; A→B→A
preserves three revisions, including the newly observed return to A. Old captures
and temporal facts remain intact. Writes are atomic under a dedicated advisory
transaction lock and a locked registry row. Outcomes expose coverage and validation.

Reads select the latest version with both actual observation and availability
**strictly before scheduled tipoff** and no later than the workbench cutoff, in
the same NBA season. Actual tip is not currently trusted/available, so scheduled
tip is the conservative existing boundary; a delayed game does not extend it.
Invalid, expired or ambiguous latest facts mask older versions. Reader integrity,
coverage and permission checks fail closed; current policy revocation also
withholds a snapshot. A new ranking after a game cannot change that game's chosen
pre-tip version. In particular, the loaded November 10, 2025 games cannot receive
Star Power from a ranking imported in October 2026. No retrospective preview
bypass exists. Source retention/review is not an assertion of a verified publication
history. This task does not support attested historical capture backfills.

## Participation and formula

ESPN `didNotPlay`, actual `MIN`, precision, team and player ID are reused. New
parsing retains independent team diagnostics and preserves the other team's rows
when one team is malformed. Unknown participation is retained as unknown; it is
not DNP. Existing old captures with global structural box errors fail closed.
Star Power requires final ESPN evidence. It checks each team independently:
unique IDs, valid team affiliation, explicit participation, nonconflicting DNP,
minutes within game length and full team-minute coverage. Minute reconciliation allows half a minute per participating row with rounded
minutes, or half a second per row with second precision. Unknown precision is
unavailable. This detects missing minutes beyond source rounding, not an
independently audited roster; tiny omissions within rounding tolerance cannot be
ruled out. No missing minutes are extrapolated. A zero-minute appearance earns no participation credit.
Statistical production is not an input to reputation.

All following settings are explicit/editable in
`config/ranking/entertainment-stars-v5.json` and the workbench:

| Setting | Initial value |
| --- | --- |
| Elite band ends at rank / value | 5 / 1.0 |
| Strong band endpoint rank / value | 20 / 0.65 |
| Moderate band endpoint rank / value | 50 / 0.30 |
| Rank 100 value | 0.05 |
| Full-participation minutes / exponent | 30 / 1 |
| Second / third star multiplier | 0.40 / 0.15 |
| Team normalization divisor | 1.55 |
| Both-team matchup share | 0.60 |
| Maximum game-score bonus | 1.5 |

Ranks 1–5 share the highest value; later values interpolate continuously between
the three declining band endpoints and rank 100. This piecewise curve gives elite
players substantially more credit than ordinary Top 100 players. Slot multipliers
are fixed to three participating players by **published rank**, not game points;
DNP, zero-minute and unknown rows consume no slot. Additional ranked participants
remain visible with zero slot weight.

`minutes_factor = min(1, actual_minutes / full_minutes) ** minutes_exponent`.
Individual raw contribution = rank value × minutes factor. Team total = weighted
sum of its three stars; team magnitude = min(1, total / normalization divisor).
Game magnitude = `(1 − both_team_share) × max(home, away) + both_team_share × sqrt(home × away)`.
Thus one star-heavy team earns some credit, and a two-sided matchup earns more.
The metric is 0–1; bonus is metric × configured maximum, rounded to four decimals.
The proposed total adds this bonus before the unchanged cap of 10. Uncapped score,
cap and rounding adjustments remain inspectable. All values are experimental,
not calibrated percentiles. Absences earn zero, without a second absence penalty.
No ranked participants yields measured zero only with a valid complete snapshot
and complete participation evidence; unavailable evidence yields null.

## Workbench and compatibility

The loopback-only workbench defaults to schema 5. It shows source edition and
actual availability, ranked player IDs/ranks, minutes/precision, explicit status,
rank values, minutes factors, slot weights, contributions, team totals, combined
magnitude, score bonus, unresolved identities and provenance. Controls expose all
formula weights, band boundaries and normalization. Source eligibility cannot be
loosened in formula controls. Preview sessions remain PostgreSQL READ ONLY /
REPEATABLE READ. Exported reviews contain private spoiler-bearing evidence and
may include licensed ranking data; keep them private under the applicable grant.

Schema 1–4 config imports and schema-1 review envelopes keep their existing
arithmetic; schema 5 requires explicit `star` plus the existing `importance`,
`player` and `pattern` settings. No legacy file silently acquires a star term.
Missing Star Power marks schema-5 previews incomplete and adds no invented bonus.
Consumer scores continue using the original production formula.

## Verification limits

Synthetic fixtures use invented player ordering, never a copied publisher Top
100. They verify parsing, all-100 validation, source/mapping revisions, duplicate
updates, A→B→A, temporal cutoffs, revoked/invalid source versions, normalized names,
aliases, trades, ambiguity, injury-exclusion semantics, full/limited/zero/DNP/unknown
participation, independent teams, top-three diminishing contributions, both-team
matchups, no stars, caps, reproducibility, old configs and read-only HTTP previews.
DOM tests verify controls, labels, contributions and safe text rendering.

Real verification reads existing ESPN evidence and the owner-database workbench;
no publisher list, fake permission or backdated snapshot is written there. A
legitimately authorized full ranking snapshot is **not available in this session**,
so end-to-end live ranked scoring is blocked on obtaining one and observing it
before an eligible game. Public page access does not satisfy that requirement.
Exact validation results and sanitized real-data checks accompany the PR and
`docs/evidence/star-power-2026-10-16.json`.

Verified locally: **453 backend tests**, **11 workbench DOM tests**, **38 frontend
tests**, frontend build and Alembic schema check passed. Real November 10 reads
found nine games/eighteen complete team participation families and 363 distinct
ESPN IDs in the stored mapping catalog. Eight existing proposed values were
preserved, all nine Star Power results were unavailable and canonical fact,
capture and score counts were unchanged.


Automation verification: 474 backend tests passed in the full suite on fresh
local PostgreSQL; the additional mapping-completion-without-refetch regression
passed separately. All 14 workbench DOM tests passed. Parser and blocked/redirect
responses, concurrent attempts, durable cadence, deduplication, roster identities,
normalized-only retention and existing read-only previews were exercised with
synthetic fixtures. Browser verification shows ready / 100 of 100, actual capture
and next-check dates. [Sanitized real evidence](evidence/ringer-automatic-2026-10-16.json)
contains counts/health/eligibility, not the publisher list.


Retrospective-policy verification: the fresh full backend run passed 477 tests,
with the existing intermittent macOS launcher descendant-cleanup PermissionError;
its targeted rerun also failed with the same platform PermissionError. All 15 DOM tests passed. New synthetic checks cover
explicit opt-in, first versus latest selection, cross-season use, report cutoff,
expired/corrupt first snapshots, strict legacy configurations, and no database
writes during fallback reads. Browser verification selected Cleveland–Orlando and
showed the 2.09 proposal, 0.8334 bonus and retrospective slate/detail labels.
[Real comparison evidence](evidence/star-power-backfill-2026-10-16.json) includes
v6 versus strict-v5 previews from the same cutoff and unchanged source timestamps.


### Shared pregame Star Power (#10 owner follow-up)

The fan guide now includes an independent, openly explained roster-star potential
component, including preseason and upcoming observed games. Missing team records
do not suppress eligible stars. Only ranking/roster evidence genuinely known
before tip is admitted; confirmed availability remains unknown. Time Machine
also requires that evidence before its saved cutoff. The same rank/slot/team
functions serve the workbench and new `postgame-stars-v3` archive model, which
uses actual verified minutes instead of adding potential and realized stars twice.
The earlier record-only limitation is superseded for this component. No
first-snapshot consumer backfill, new collection, old-archive rewrite or global
media exception is introduced. See [Pregame expectation](PREGAME_EXPECTATION.md).
